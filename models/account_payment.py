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
    approval_rule_id = fields.Many2one(
        "aerotec.approval.rule",
        string="Regla aplicable",
        compute="_compute_approval_info",
        store=True,
    )
    approver_ids = fields.Many2many(
        "res.users",
        "account_payment_approver_rel",
        "payment_id",
        "user_id",
        string="Autorizadores requeridos",
        compute="_compute_approval_info",
        store=True,
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
                payment.approval_rule_id = False
                payment.approver_ids = False
                payment.requires_approval = False
                continue
            rule = Rule._find_for_document(
                amount=payment.amount,
                currency=payment.currency_id,
                company=payment.company_id,
                doc_type="payment",
            )
            payment.approval_rule_id = rule
            payment.approver_ids = rule.user_ids if rule else False
            payment.requires_approval = bool(rule)

    @api.depends("approver_ids")
    @api.depends_context("uid")
    def _compute_is_current_user_approver(self):
        for payment in self:
            payment.is_current_user_approver = self.env.user in payment.approver_ids

    @api.depends("approver_ids", "approved_by_id", "approval_state")
    @api.depends_context("uid")
    def _compute_is_current_user_rejecter(self):
        for payment in self:
            if payment.approval_state == "pending":
                payment.is_current_user_rejecter = self.env.user in payment.approver_ids
            elif payment.approval_state == "approved":
                payment.is_current_user_rejecter = self.env.user == payment.approved_by_id
            else:
                payment.is_current_user_rejecter = False

    def action_request_approval(self):
        for payment in self:
            if payment.payment_type != "outbound":
                raise UserError(
                    _("Solo se puede solicitar aprobación para pagos a proveedores.")
                )
            if not payment.requires_approval:
                raise UserError(
                    _("Este pago no supera ningún tope configurado y no requiere aprobación.")
                )
            if payment.approval_state in ("pending", "approved"):
                labels = dict(self._fields["approval_state"].selection)
                raise UserError(
                    _(
                        "El pago ya está en estado '%(state)s'.",
                        state=labels.get(payment.approval_state, ""),
                    )
                )
            payment.write({"approval_state": "pending"})
            note = _(
                "El pago a <b>%(partner)s</b> por <b>%(currency)s %(amount)s</b> "
                "requiere su autorización.",
                partner=payment.partner_id.name or "",
                currency=payment.currency_id.name or "",
                amount=f"{payment.amount:,.2f}",
            )
            for approver in payment.approver_ids:
                payment.activity_schedule(
                    "mail.mail_activity_data_todo",
                    user_id=approver.id,
                    summary=_("Pago a proveedor pendiente de su autorización"),
                    note=note,
                )

    def action_approve_payment(self):
        for payment in self:
            if payment.approval_state != "pending":
                raise UserError(
                    _("Solo se pueden aprobar pagos que están pendientes de aprobación.")
                )
            if self.env.user not in payment.approver_ids:
                raise UserError(
                    _("No tiene autorización para aprobar este pago.")
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
            if payment.approval_state == "pending" and self.env.user not in payment.approver_ids:
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
            payment.write({"approval_state": "not_required"})
            payment.activity_unlink(["mail.mail_activity_data_todo"])

    def action_reset_payment_approval(self):
        """Restablece el estado tras un rechazo para re-solicitar aprobación."""
        for payment in self:
            if payment.approval_state != "rejected":
                raise UserError(_("Solo se pueden restablecer pagos rechazados."))
            payment.write({"approval_state": "not_required"})

    def action_post(self):
        for payment in self:
            if (
                payment.payment_type == "outbound"
                and payment.requires_approval
                and payment.approval_state != "approved"
            ):
                labels = dict(self._fields["approval_state"].selection)
                approvers = ", ".join(payment.approver_ids.mapped("name")) or "un autorizador configurado"
                raise UserError(
                    _(
                        "El pago requiere la aprobación de: %(users)s.\n"
                        "Estado actual: %(state)s.",
                        users=approvers,
                        state=labels.get(payment.approval_state, payment.approval_state),
                    )
                )
        return super().action_post()
