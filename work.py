# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.

from decimal import Decimal
from trytond.model import ModelView, ModelSQL, fields
from trytond.pool import PoolMeta, Pool
from trytond.pyson import Eval
from trytond.transaction import Transaction

__all__ = ['ProjectExpense', 'Work']
__metaclass__ = PoolMeta


class ProjectExpense(ModelSQL, ModelView):
    'Project Expense'
    __name__ = 'project.work.expense'

    name = fields.Char('Name', required=True, select=True)
    product = fields.Many2One('product.product', 'Product', required=True,
        on_change=['product', 'unit', 'quantity', 'name', 'work'],
        depends=['work'])
    quantity = fields.Float('Quantity', digits=(16, Eval('unit_digits', 2)),
        depends=['unit_digits'])
    unit = fields.Many2One('product.uom', 'Unit')
    unit_digits = fields.Function(fields.Integer('Unit Digits',
        on_change_with=['unit']), 'on_change_with_unit_digits')
    product_uom_category = fields.Function(
        fields.Many2One('product.uom.category', 'Product Uom Category',
            on_change_with=['product']),
        'on_change_with_product_uom_category')
    unit_price = fields.Numeric('Unit Price', digits=(16, 4))
    work = fields.Many2One('project.work', 'Work')
    invoice_line = fields.Many2One('account.invoice.line', 'Invoice Line',
        readonly=True)

    @classmethod
    def copy(cls, records, default=None):
        if default is None:
            default = {}
        default = default.copy()
        default.setdefault('invoice_line', None)
        return super(ProjectExpense, cls).copy(records, default=default)

    def on_change_product(self):
        Product = Pool().get('product.product')

        if not self.product:
            return {}
        res = {}

        party = None
        party_context = {}
        party = self.work.party
        if party.lang:
            party_context['language'] = party.lang.code

        category = self.product.default_uom.category
        if not self.unit or self.unit not in category.uoms:
            res['unit'] = self.product.default_uom.id
            res['unit.rec_name'] = self.product.default_uom.rec_name
            res['unit_digits'] = self.product.default_uom.digits

        res['unit_price'] = self.product.list_price
        if res['unit_price']:
            res['unit_price'] = res['unit_price'].quantize(
                Decimal(1) / 10 ** self.__class__.unit_price.digits[1])

        if not self.name:
            with Transaction().set_context(party_context):
                res['name'] = Product(self.product.id).rec_name

        return res

    def on_change_with_unit_digits(self, name=None):
        if self.unit:
            return self.unit.digits
        return 2

    def on_change_with_product_uom_category(self, name=None):
        if self.product:
            return self.product.default_uom_category.id

    @classmethod
    def invoice(cls, expenses):
        pool = Pool()
        Invoice = pool.get('account.invoice')
        InvoiceLine = pool.get('account.invoice.line')
        for expense in expenses:

            if expense.invoice_line:
                continue

            with Transaction().set_context({
                            'invoice_type': 'out_invoice',
                            'standalone': True,
                            }):
                invoice = Invoice()
                invoice.party = expense.work.party

                invoiceline = InvoiceLine()
                invoiceline.party = expense.work.party
                invoiceline.product = expense.product
                invoiceline.description = expense.name
                invoiceline.unit_price = expense.unit_price
                invoiceline.unit = expense.unit
                invoiceline.account = expense.product.account_revenue_used

                taxes = []
                pattern = invoiceline._get_tax_rule_pattern()
                party = invoice.party
                for tax in expense.product.customer_taxes_used:
                    if party.customer_tax_rule:
                        tax_ids = party.customer_tax_rule.apply(tax, pattern)
                        if tax_ids:
                            taxes.extend(tax_ids)
                        continue
                    taxes.append(tax.id)
                if party.customer_tax_rule:
                    tax_ids = party.customer_tax_rule.apply(None, pattern)
                    if tax_ids:
                        taxes.extend(tax_ids)

                invoiceline.taxes = taxes
                invoiceline.type = 'line'
                invoiceline.invoice_type = 'out_invoice'
                invoiceline.quantity = expense.quantity
                invoiceline.save()

                expense.invoice_line = invoiceline.id
                expense.save()


class Work:
    __name__ = 'project.work'

    expenses = fields.One2Many('project.work.expense', 'work', 'Expenses')

    def _get_expenses_to_invoice(self, test=None):
        lines = []
        if test is None:
            test = self._test_group_invoice()

        lines += self.expenses
        for children in self.children:
            if children.type == 'project':
                if test != children._test_group_invoice():
                    continue
            lines += children._get_expenses_to_invoice(test=test)
        return lines

    @classmethod
    @ModelView.button
    def invoice(cls, works):
        Expense = Pool().get('project.work.expense')
        expenses = []
        for work in works:
            expenses += work._get_expenses_to_invoice()
        Expense.invoice(expenses)
        super(Work, cls).invoice(works)
