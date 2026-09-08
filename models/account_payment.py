from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountPayment(models.Model):
    _inherit = "account.payment"

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
        "account_payment_approval_rule_rel",
        "payment_id",
        "rule_id",
        string="Reglas aplicables",
        compute="_compute_approval_info",
        store=True,
    )
    approver_ids = fields.Many2many(
        "res.users",
        "account_payment_approver_rel",
        "payment_id",
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
        "aprobar o rechazar el pago.",
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

    @api.depends("payment_type", "amount", "currency_id", "company_id")
    def _compute_approval_info(self):
        Rule = self.env["aerotec.approval.rule"]
        for payment in self:
            if payment.payment_type != "outbound":
                payment.approval_rule_ids = False
                payment.approver_ids = False
                payment.requires_approval = False
                payment.approval_blocked = False
                continue
            res = Rule._evaluate_for_document(
                amount=payment.amount,
                currency=payment.currency_id,
                company=payment.company_id,
                doc_type="payment",
            )
            payment.approval_rule_ids = res["rules"]
            payment.approver_ids = res["users"]
            payment.requires_approval = res["status"] == "required"
            payment.approval_blocked = res["status"] == "blocked"

    @api.depends("approver_id")
    @api.depends_context("uid")
    def _compute_is_current_user_approver(self):
        for payment in self:
            payment.is_current_user_approver = self.env.user == payment.approver_id

    @api.depends("approver_id", "approved_by_id", "approval_state")
    @api.depends_context("uid")
    def _compute_is_current_user_rejecter(self):
        for payment in self:
            if payment.approval_state == "pending":
                payment.is_current_user_rejecter = self.env.user == payment.approver_id
            elif payment.approval_state == "approved":
                payment.is_current_user_rejecter = self.env.user == payment.approved_by_id
            else:
                payment.is_current_user_rejecter = False

    def action_request_approval(self):
        self.ensure_one()
        if self.payment_type != "outbound":
            raise UserError(
                _("Solo se puede solicitar aprobación para pagos a proveedores.")
            )
        if self.approval_blocked:
            raise UserError(
                _(
                    "Este pago está fuera de todos los rangos de autorización "
                    "configurados. No hay ningún usuario habilitado para autorizarlo."
                )
            )
        if not self.requires_approval:
            raise UserError(
                _("Este pago no supera ningún tope configurado y no requiere aprobación.")
            )
        if self.approval_state in ("pending", "approved"):
            labels = dict(self._fields["approval_state"].selection)
            raise UserError(
                _(
                    "El pago ya está en estado '%(state)s'.",
                    state=labels.get(self.approval_state, ""),
                )
            )
        return {
            "type": "ir.actions.act_window",
            "name": _("Solicitar aprobación"),
            "res_model": "aerotec.approval.request.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_payment_id": self.id},
        }

    def _do_request_approval(self, approver, note=False):
        """Registra la solicitud de aprobación asignando un autorizador único."""
        self.ensure_one()
        if approver not in self.approver_ids:
            raise UserError(
                _("El autorizador seleccionado no está habilitado para este pago.")
            )
        vals = {"approval_state": "pending", "approver_id": approver.id}
        if note:
            vals["approval_notes"] = note
        self.write(vals)
        body = _(
            "El pago a <b>%(partner)s</b> por <b>%(currency)s %(amount)s</b> "
            "requiere su autorización.",
            partner=self.partner_id.name or "",
            currency=self.currency_id.name or "",
            amount=f"{self.amount:,.2f}",
        )
        if note:
            body += _("<br/>Nota del solicitante: %(note)s", note=note)
        self._notify_approver(
            body, summary=_("Pago a proveedor pendiente de su autorización")
        )

    def _notify_approver(self, note, summary):
        for payment in self:
            if not payment.approver_id:
                continue
            payment.activity_schedule(
                "mail.mail_activity_data_todo",
                user_id=payment.approver_id.id,
                summary=summary,
                note=note,
            )

    def _reset_approval_for_draft(self):
        for payment in self:
            old_approver = payment.approved_by_id
            old_date = payment.approval_date
            old_amount = payment.amount
            old_currency = payment.currency_id.name or ""
            if payment.approval_blocked or not payment.requires_approval:
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
            payment.write(vals)
            payment.message_post(
                body=_(
                    "⚠️ %(user)s restableció este pago a borrador. "
                    "Se anuló la aprobación previa de <b>%(approver)s</b> "
                    "del %(date)s, otorgada para un importe de "
                    "%(currency)s %(amount)s. El pago vuelve a estado "
                    "'Pendiente de aprobación' y debe ser re-autorizado "
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
                    "El pago a <b>%(partner)s</b> por <b>%(currency)s %(amount)s</b> "
                    "fue devuelto a borrador y requiere nuevamente su autorización.",
                    partner=payment.partner_id.name or "",
                    currency=payment.currency_id.name or "",
                    amount=f"{payment.amount:,.2f}",
                )
                payment._notify_approver(
                    note,
                    summary=_("Pago a proveedor pendiente de su autorización"),
                )

    def action_approve_payment(self):
        for payment in self:
            if payment.approval_state != "pending":
                raise UserError(
                    _("Solo se pueden aprobar pagos que están pendientes de aprobación.")
                )
            if self.env.user != payment.approver_id:
                raise UserError(
                    _("No tiene autorización para aprobar este pago.")
                )
            if payment.approver_id not in payment.approver_ids:
                raise UserError(
                    _(
                        "El autorizador asignado ya no está habilitado para el monto "
                        "actual del pago. Cancele la solicitud y vuelva a solicitarla."
                    )
                )
            payment.write({
                "approval_state": "approved",
                "approval_date": fields.Datetime.now(),
                "approved_by_id": self.env.user.id,
            })
            payment.activity_unlink(["mail.mail_activity_data_todo"])

    def action_reject_payment(self):
        for payment in self:
            if payment.approval_state not in ("pending", "approved"):
                raise UserError(_("Solo se pueden rechazar pagos pendientes o aprobados."))
            if payment.approval_state == "pending" and self.env.user != payment.approver_id:
                raise UserError(
                    _("No tiene autorización para rechazar este pago.")
                )
            if payment.approval_state == "approved" and self.env.user != payment.approved_by_id:
                raise UserError(
                    _(
                        "Solo '%(user)s' puede revertir su propia aprobación.",
                        user=payment.approved_by_id.name,
                    )
                )
            payment.write({
                "approval_state": "rejected",
                "approval_date": False,
                "approved_by_id": False,
            })
            payment.activity_unlink(["mail.mail_activity_data_todo"])

    def action_cancel_approval_request(self):
        """El creador cancela la solicitud pendiente."""
        for payment in self:
            if payment.approval_state != "pending":
                raise UserError(_("Solo se puede cancelar una solicitud pendiente."))
            payment.write({"approval_state": "not_required", "approver_id": False})
            payment.activity_unlink(["mail.mail_activity_data_todo"])

    def action_reset_payment_approval(self):
        """Restablece el estado tras un rechazo para re-solicitar aprobación."""
        for payment in self:
            if payment.approval_state != "rejected":
                raise UserError(_("Solo se pueden restablecer pagos rechazados."))
            payment.write({"approval_state": "not_required", "approver_id": False})

    def action_post(self):
        for payment in self:
            if payment.payment_type != "outbound":
                continue
            if payment.approval_blocked:
                raise UserError(
                    _(
                        "El pago a %(partner)s por %(currency)s %(amount)s está fuera de "
                        "todos los rangos de autorización configurados: no hay ningún "
                        "usuario habilitado para autorizarlo. Cree o ajuste una regla de "
                        "autorización que cubra este monto.",
                        partner=payment.partner_id.name or "",
                        currency=payment.currency_id.name or "",
                        amount=f"{payment.amount:,.2f}",
                    )
                )
            if payment.requires_approval and payment.approval_state != "approved":
                labels = dict(self._fields["approval_state"].selection)
                approver = payment.approver_id.name or "un autorizador configurado"
                raise UserError(
                    _(
                        "El pago requiere la aprobación de: %(user)s.\n"
                        "Estado actual: %(state)s.",
                        user=approver,
                        state=labels.get(payment.approval_state, payment.approval_state),
                    )
                )
        return super().action_post()

    def action_draft(self):
        to_reset = self.filtered(
            lambda p: p.payment_type == "outbound" and p.approval_state == "approved"
        )
        result = super().action_draft()
        to_reset._reset_approval_for_draft()
        return result
