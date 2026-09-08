from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = "account.move"

    approval_state = fields.Selection(
        [
            ("not_required", "Sin aprobación pendiente"),
            ("pending", "Pendiente de aprobación"),
            ("approved", "Aprobada"),
            ("rejected", "Rechazada"),
        ],
        string="Estado de aprobación",
        default="not_required",
        copy=False,
        tracking=True,
    )
    approval_rule_ids = fields.Many2many(
        "aerotec.approval.rule",
        "account_move_approval_rule_rel",
        "move_id",
        "rule_id",
        string="Reglas aplicables",
        compute="_compute_approval_info",
        store=True,
    )
    approver_ids = fields.Many2many(
        "res.users",
        "account_move_approver_rel",
        "move_id",
        "user_id",
        string="Autorizadores habilitados",
        compute="_compute_approval_info",
        store=True,
    )
    approver_id = fields.Many2one(
        "res.users",
        string="Autorizador asignado",
        copy=False,
        tracking=True,
        help="Usuario seleccionado al solicitar la aprobación. Solo esta persona puede "
        "aprobar o rechazar el comprobante.",
    )
    approved_by_id = fields.Many2one(
        "res.users",
        string="Aprobado/Rechazado por",
        readonly=True,
        copy=False,
    )
    requires_approval = fields.Boolean(
        string="Requiere aprobación",
        compute="_compute_approval_info",
        store=True,
    )
    approval_blocked = fields.Boolean(
        string="Sin autorizador disponible",
        compute="_compute_approval_info",
        store=True,
        help="El monto queda fuera de todos los rangos de autorización configurados: "
        "no hay ningún usuario habilitado para autorizarlo.",
    )
    is_current_user_approver = fields.Boolean(
        compute="_compute_is_current_user_approver",
        store=False,
    )
    is_current_user_rejecter = fields.Boolean(
        compute="_compute_is_current_user_rejecter",
        store=False,
    )
    approval_date = fields.Datetime(
        string="Fecha de aprobación",
        readonly=True,
        copy=False,
    )
    approval_notes = fields.Text(
        string="Notas de la aprobación",
        copy=False,
    )

    @api.depends("move_type", "amount_total", "currency_id", "company_id")
    def _compute_approval_info(self):
        Rule = self.env["aerotec.approval.rule"]
        for move in self:
            if move.move_type != "in_invoice":
                move.approval_rule_ids = False
                move.approver_ids = False
                move.requires_approval = False
                move.approval_blocked = False
                continue
            res = Rule._evaluate_for_document(
                amount=move.amount_total,
                currency=move.currency_id,
                company=move.company_id,
                doc_type="invoice",
            )
            move.approval_rule_ids = res["rules"]
            move.approver_ids = res["users"]
            move.requires_approval = res["status"] == "required"
            move.approval_blocked = res["status"] == "blocked"

    @api.depends("approver_id")
    @api.depends_context("uid")
    def _compute_is_current_user_approver(self):
        for move in self:
            move.is_current_user_approver = self.env.user == move.approver_id

    @api.depends("approver_id", "approved_by_id", "approval_state")
    @api.depends_context("uid")
    def _compute_is_current_user_rejecter(self):
        for move in self:
            if move.approval_state == "pending":
                move.is_current_user_rejecter = self.env.user == move.approver_id
            elif move.approval_state == "approved":
                move.is_current_user_rejecter = self.env.user == move.approved_by_id
            else:
                move.is_current_user_rejecter = False

    def action_request_approval(self):
        self.ensure_one()
        if self.move_type != "in_invoice":
            raise UserError(
                _("Solo se puede solicitar aprobación para facturas de proveedor.")
            )
        if self.approval_blocked:
            raise UserError(
                _(
                    "Esta factura está fuera de todos los rangos de autorización "
                    "configurados. No hay ningún usuario habilitado para autorizarla."
                )
            )
        if not self.requires_approval:
            raise UserError(
                _("Esta factura no supera ningún tope configurado y no requiere aprobación.")
            )
        if self.approval_state in ("pending", "approved"):
            labels = dict(self._fields["approval_state"].selection)
            raise UserError(
                _(
                    "La factura ya está en estado '%(state)s'.",
                    state=labels.get(self.approval_state, ""),
                )
            )
        return {
            "type": "ir.actions.act_window",
            "name": _("Solicitar aprobación"),
            "res_model": "aerotec.approval.request.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_move_id": self.id},
        }

    def _do_request_approval(self, approver, note=False):
        """Registra la solicitud de aprobación asignando un autorizador único."""
        self.ensure_one()
        if approver not in self.approver_ids:
            raise UserError(
                _("El autorizador seleccionado no está habilitado para esta factura.")
            )
        vals = {"approval_state": "pending", "approver_id": approver.id}
        if note:
            vals["approval_notes"] = note
        self.write(vals)
        body = _(
            "La factura <b>%(ref)s</b> de <b>%(partner)s</b> "
            "por <b>%(currency)s %(amount)s</b> requiere su autorización.",
            ref=self.name or self.ref or "borrador",
            partner=self.partner_id.name or "",
            currency=self.currency_id.name or "",
            amount=f"{self.amount_total:,.2f}",
        )
        if note:
            body += _("<br/>Nota del solicitante: %(note)s", note=note)
        self._notify_approver(
            body, summary=_("Factura de proveedor pendiente de su autorización")
        )

    def _notify_approver(self, note, summary):
        for move in self:
            if not move.approver_id:
                continue
            move.activity_schedule(
                "mail.mail_activity_data_todo",
                user_id=move.approver_id.id,
                summary=summary,
                note=note,
            )

    def _reset_approval_for_draft(self):
        for move in self:
            old_approver = move.approved_by_id
            old_date = move.approval_date
            old_amount = move.amount_total
            old_currency = move.currency_id.name or ""
            if move.approval_blocked or not move.requires_approval:
                new_state = "not_required"
            else:
                new_state = "pending"
            vals = {
                "approval_state": new_state,
                "approved_by_id": False,
                "approval_date": False,
            }
            if new_state == "not_required":
                vals["approver_id"] = False
            move.write(vals)
            move.message_post(
                body=_(
                    "⚠️ %(user)s restableció esta factura a borrador. "
                    "Se anuló la aprobación previa de <b>%(approver)s</b> "
                    "del %(date)s, otorgada para un importe de "
                    "%(currency)s %(amount)s. La factura vuelve a estado "
                    "'Pendiente de aprobación' y debe ser re-autorizada "
                    "antes de confirmarse.",
                    user=self.env.user.name,
                    approver=old_approver.name or "-",
                    date=old_date or "-",
                    currency=old_currency,
                    amount=f"{old_amount:,.2f}",
                )
            )
            if new_state == "pending":
                note = _(
                    "La factura <b>%(ref)s</b> de <b>%(partner)s</b> "
                    "por <b>%(currency)s %(amount)s</b> fue devuelta a "
                    "borrador y requiere nuevamente su autorización.",
                    ref=move.name or move.ref or "borrador",
                    partner=move.partner_id.name or "",
                    currency=move.currency_id.name or "",
                    amount=f"{move.amount_total:,.2f}",
                )
                move._notify_approver(
                    note,
                    summary=_("Factura de proveedor pendiente de su autorización"),
                )

    def action_approve_invoice(self):
        for move in self:
            if move.approval_state != "pending":
                raise UserError(
                    _("Solo se pueden aprobar facturas que están pendientes de aprobación.")
                )
            if self.env.user != move.approver_id:
                raise UserError(
                    _("No tiene autorización para aprobar esta factura.")
                )
            if move.approver_id not in move.approver_ids:
                raise UserError(
                    _(
                        "El autorizador asignado ya no está habilitado para el monto "
                        "actual de la factura. Cancele la solicitud y vuelva a solicitarla."
                    )
                )
            move.write({
                "approval_state": "approved",
                "approval_date": fields.Datetime.now(),
                "approved_by_id": self.env.user.id,
            })
            move.activity_unlink(["mail.mail_activity_data_todo"])

    def action_reject_invoice(self):
        for move in self:
            if move.approval_state not in ("pending", "approved"):
                raise UserError(
                    _("Solo se pueden rechazar facturas pendientes o aprobadas.")
                )
            if move.approval_state == "pending" and self.env.user != move.approver_id:
                raise UserError(
                    _("No tiene autorización para rechazar esta factura.")
                )
            if move.approval_state == "approved" and self.env.user != move.approved_by_id:
                raise UserError(
                    _(
                        "Solo '%(user)s' puede revertir su propia aprobación.",
                        user=move.approved_by_id.name,
                    )
                )
            move.write({
                "approval_state": "rejected",
                "approval_date": False,
                "approved_by_id": False,
            })
            move.activity_unlink(["mail.mail_activity_data_todo"])

    def action_cancel_approval_request(self):
        """El creador cancela la solicitud de aprobación para poder editar la factura."""
        for move in self:
            if move.approval_state != "pending":
                raise UserError(_("Solo se puede cancelar una solicitud pendiente."))
            move.write({"approval_state": "not_required", "approver_id": False})
            move.activity_unlink(["mail.mail_activity_data_todo"])

    def action_reset_invoice_approval(self):
        """Restablece el estado para re-solicitar aprobación tras un rechazo."""
        for move in self:
            if move.approval_state != "rejected":
                raise UserError(_("Solo se pueden restablecer facturas rechazadas."))
            move.write({"approval_state": "not_required", "approver_id": False})

    def action_post(self):
        for move in self:
            if move.move_type != "in_invoice":
                continue
            if move.approval_blocked:
                raise UserError(
                    _(
                        "La factura '%(name)s' por %(currency)s %(amount)s está fuera de "
                        "todos los rangos de autorización configurados: no hay ningún "
                        "usuario habilitado para autorizarla. Cree o ajuste una regla de "
                        "autorización que cubra este monto.",
                        name=move.name or "",
                        currency=move.currency_id.name or "",
                        amount=f"{move.amount_total:,.2f}",
                    )
                )
            if move.requires_approval and move.approval_state != "approved":
                labels = dict(self._fields["approval_state"].selection)
                approver = move.approver_id.name or "un autorizador configurado"
                raise UserError(
                    _(
                        "La factura '%(name)s' requiere la aprobación de: %(user)s.\n"
                        "Estado actual: %(state)s.",
                        name=move.name or "",
                        user=approver,
                        state=labels.get(move.approval_state, move.approval_state),
                    )
                )
        return super().action_post()

    def button_draft(self):
        to_reset = self.filtered(
            lambda m: m.move_type == "in_invoice" and m.approval_state == "approved"
        )
        result = super().button_draft()
        to_reset._reset_approval_for_draft()
        return result
