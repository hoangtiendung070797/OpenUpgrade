# Copyright 2021 ForgeFlow S.L.  <https://www.forgeflow.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
import logging

from openupgradelib import openupgrade

from odoo.tools.translate import _

_logger = logging.getLogger(__name__)


def _create_hooks(env):
    def _check_fiscalyear_lock_date(self):
        return True

    def _check_tax_lock_date(self):
        return True

    def _check_reconciliation(self):
        return True

    # create hooks
    _check_fiscalyear_lock_date._original_method = type(
        env["account.move"]
    )._check_fiscalyear_lock_date
    type(env["account.move"])._check_fiscalyear_lock_date = _check_fiscalyear_lock_date
    _check_tax_lock_date._original_method = type(
        env["account.move.line"]
    )._check_tax_lock_date
    type(env["account.move.line"])._check_tax_lock_date = _check_tax_lock_date
    _check_reconciliation._original_method = type(
        env["account.move.line"]
    )._check_reconciliation
    type(env["account.move.line"])._check_reconciliation = _check_reconciliation


def _delete_hooks(env):
    # delete hooks
    type(env["account.move"])._check_fiscalyear_lock_date = type(
        env["account.move"]
    )._check_fiscalyear_lock_date._original_method
    type(env["account.move.line"])._check_tax_lock_date = type(
        env["account.move.line"]
    )._check_tax_lock_date._original_method
    type(env["account.move.line"])._check_reconciliation = type(
        env["account.move.line"]
    )._check_reconciliation._original_method


def fill_account_journal_posted_before(env):
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE account_move
        SET posted_before = TRUE
        WHERE state = 'posted'""",
    )


def fill_code_prefix_end_field(env):
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE account_group
        SET code_prefix_end = code_prefix_start
        """,
    )


def fill_default_account_id_field(env):
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE account_journal
        SET default_account_id = {0}
        WHERE {0} = {1} OR ({0} IS NOT NULL AND {1} IS NULL);
        UPDATE account_journal
        SET default_account_id = {1}
        WHERE {0} IS NULL AND {1} IS NOT NULL
        """.format(
            openupgrade.get_legacy_name("default_credit_account_id"),
            openupgrade.get_legacy_name("default_debit_account_id"),
        ),
    )


def fill_payment_id_and_statement_line_id_fields(env):
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE account_move_line aml
        SET payment_id = am.payment_id
        FROM account_move am
        WHERE am.id = aml.move_id AND am.payment_id IS NOT NULL
        """,
    )
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE account_move_line aml
        SET statement_line_id = am.statement_line_id
        FROM account_move am
        WHERE am.id = aml.move_id AND am.statement_line_id IS NOT NULL
        """,
    )


def fill_partial_reconcile_debit_and_credit_amounts(env):
    # compute debit and credit amount when currencies are the same
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE account_partial_reconcile
        SET debit_amount_currency = amount, credit_amount_currency = amount
        WHERE debit_amount_currency IS NULL AND credit_amount_currency is NULL
            AND credit_currency_id = debit_currency_id
       """,
    )
    # compute debit and credit amount when currencies are different
    partial_reconcile_lines = (
        env["account.partial.reconcile"]
        .search(
            [
                ("debit_amount_currency", "=", False),
                ("credit_amount_currency", "=", False),
            ]
        )
        .filtered(lambda line: line.credit_currency_id != line.debit_currency_id)
    )
    for line in partial_reconcile_lines:
        line.debit_amount_currency = line.company_currency_id._convert(
            line.amount,
            line.debit_currency_id,
            line.company_id,
            line.credit_move_id.date,
        )
        line.credit_amount_currency = line.company_currency_id._convert(
            line.amount,
            line.credit_currency_id,
            line.company_id,
            line.debit_move_id.date,
        )


def create_account_reconcile_model_lines(env):
    openupgrade.logged_query(
        env.cr,
        """
        INSERT INTO account_reconcile_model_line (model_id, company_id,
            sequence, account_id, journal_id, label, amount_type,
            force_tax_included, amount, amount_string, analytic_account_id,
            create_uid, create_date, write_uid, write_date)
        SELECT id, company_id, 10, account_id, journal_id, label,
            amount_type, force_tax_included,
            CASE WHEN amount_type = 'regex' THEN 0 ELSE amount END as amount,
            CASE WHEN amount_type = 'regex' THEN amount_from_label_regex
                ELSE amount || '' END as amount_string,
            analytic_account_id, create_uid, create_date, write_uid, write_date
        FROM (
            SELECT arm.* FROM account_reconcile_model arm
            LEFT JOIN ir_model_data imd ON (
                imd.model = 'account.reconcile.model' AND imd.res_id = arm.id)
            WHERE imd.id IS NULL) arm1
        WHERE rule_type != 'invoice_matching' OR (rule_type = 'invoice_matching'
            AND match_total_amount AND match_total_amount_param < 100.0)
        UNION ALL
        SELECT id, company_id, 20, second_account_id, second_journal_id,
            second_label, second_amount_type, force_second_tax_included,
            CASE WHEN second_amount_type = 'regex' THEN 0
                ELSE second_amount END as amount,
            CASE WHEN second_amount_type = 'regex' THEN second_amount_from_label_regex
                ELSE second_amount || '' END as amount_string,
            second_analytic_account_id, create_uid, create_date, write_uid, write_date
        FROM (
            SELECT arm.* FROM account_reconcile_model arm
            LEFT JOIN ir_model_data imd ON (
                imd.model = 'account.reconcile.model' AND imd.res_id = arm.id)
            WHERE imd.id IS NULL) arm2
        WHERE has_second_line AND (rule_type != 'invoice_matching' OR (
            rule_type = 'invoice_matching' AND match_total_amount
            AND match_total_amount_param < 100.0))
        ORDER BY id""",
    )
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE account_reconcile_model_analytic_tag_rel rel
        SET account_reconcile_model_line_id = arml.id
        FROM account_reconcile_model_line arml
        WHERE arml.model_id = rel.account_reconcile_model_id""",
    )
    openupgrade.logged_query(
        env.cr,
        """
        DELETE FROM account_reconcile_model_analytic_tag_rel
        WHERE account_reconcile_model_line_id IS NULL""",
    )
    openupgrade.logged_query(
        env.cr,
        """
        INSERT INTO account_reconcile_model_analytic_tag_rel (
            account_reconcile_model_line_id, account_analytic_tag_id)
        SELECT arml.id, rel.account_analytic_tag_id
        FROM account_reconcile_model_second_analytic_tag_rel rel
        JOIN account_reconcile_model_line arml
            ON rel.account_reconcile_model_id = arml.model_id""",
    )
    openupgrade.logged_query(
        env.cr,
        """
        INSERT INTO account_reconcile_model_line_account_tax_rel (
            account_reconcile_model_line_id, account_tax_id)
        SELECT arml.id, rel.account_tax_id
        FROM account_reconcile_model_account_tax_rel rel
        JOIN account_reconcile_model_line arml
            ON rel.account_reconcile_model_id = arml.model_id""",
    )
    openupgrade.logged_query(
        env.cr,
        """
        INSERT INTO account_reconcile_model_line_account_tax_rel (
            account_reconcile_model_line_id, account_tax_id)
        SELECT arml.id, rel.account_tax_id
        FROM account_reconcile_model_account_tax_bis_rel rel
        JOIN account_reconcile_model_line arml
            ON rel.account_reconcile_model_id = arml.model_id""",
    )


def create_account_reconcile_model_template_lines(env):
    openupgrade.logged_query(
        env.cr,
        """
        INSERT INTO account_reconcile_model_line_template (model_id,
            sequence, account_id, label, amount_type,
            force_tax_included, amount_string,
            create_uid, create_date, write_uid, write_date)
        SELECT id, 10, account_id, label,
            amount_type, force_tax_included,
            CASE WHEN amount_type = 'regex' THEN amount_from_label_regex
                ELSE amount::varchar END as amount_string,
            create_uid, create_date, write_uid, write_date
        FROM (
            SELECT armt.* FROM account_reconcile_model_template armt
            LEFT JOIN ir_model_data imd ON (
                imd.model = 'account.reconcile.model.template'
                    AND imd.res_id = armt.id)
            WHERE imd.id IS NULL) armt1
        WHERE rule_type != 'invoice_matching' OR (rule_type = 'invoice_matching'
            AND match_total_amount AND match_total_amount_param < 100.0)
        UNION ALL
        SELECT id, 20, second_account_id,
            second_label, second_amount_type, force_second_tax_included,
            CASE WHEN second_amount_type = 'regex' THEN second_amount_from_label_regex
                ELSE second_amount::varchar END as amount_string,
            create_uid, create_date, write_uid, write_date
        FROM (
            SELECT armt.* FROM account_reconcile_model_template armt
            LEFT JOIN ir_model_data imd ON (
                imd.model = 'account.reconcile.model.template'
                    AND imd.res_id = armt.id)
            WHERE imd.id IS NULL) armt2
        WHERE has_second_line AND (rule_type != 'invoice_matching' OR (
            rule_type = 'invoice_matching' AND match_total_amount
            AND match_total_amount_param < 100.0))
        ORDER BY id""",
    )
    openupgrade.logged_query(
        env.cr,
        """
        INSERT INTO account_reconcile_model_line_template_account_tax_template_rel (
            account_reconcile_model_line_template_id, account_tax_template_id)
        SELECT armlt.id, rel.account_tax_template_id
        FROM account_reconcile_model_template_account_tax_template_rel rel
        JOIN account_reconcile_model_line_template armlt
            ON rel.account_reconcile_model_template_id = armlt.model_id""",
    )
    openupgrade.logged_query(
        env.cr,
        """
        INSERT INTO account_reconcile_model_line_template_account_tax_template_rel (
            account_reconcile_model_line_template_id, account_tax_template_id)
        SELECT armlt.id, rel.account_tax_template_id
        FROM account_reconcile_model_tmpl_account_tax_bis_rel rel
        JOIN account_reconcile_model_line_template armlt
            ON rel.account_reconcile_model_template_id = armlt.model_id""",
    )


def create_account_tax_report_lines(env):
    openupgrade.logged_query(
        env.cr,
        """
        ALTER TABLE account_tax_report
        ADD COLUMN root_line_id integer""",
    )
    openupgrade.logged_query(
        env.cr,
        """
        INSERT INTO account_tax_report (name, country_id, root_line_id,
            create_uid, create_date, write_uid, write_date)
        SELECT name, country_id, id, create_uid, create_date, write_uid, write_date
        FROM account_tax_report_line
        WHERE parent_id IS NULL
        """,
    )
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE account_tax_report_line atrl
        SET report_id = atr.id
        FROM account_tax_report atr
        WHERE atr.root_line_id = atrl.id
        """,
    )
    while True:
        openupgrade.logged_query(
            env.cr,
            """
            UPDATE account_tax_report_line atrl
            SET report_id = atrl2.report_id
            FROM account_tax_report_line atrl2
            WHERE atrl.parent_id = atrl2.id AND atrl.report_id IS NULL
            RETURNING atrl.id""",
        )
        if not env.cr.fetchone():
            break


def post_statements_with_unreconciled_lines(env):
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE account_bank_statement bst
        SET state = 'posted'
        FROM account_bank_statement_line bstl
        WHERE bst.state = 'confirm' AND bstl.statement_id = bst.id
            AND bstl.is_reconciled IS DISTINCT FROM TRUE
        """,
    )


def pass_bank_statement_line_note_to_journal_entry_narration(env):
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE account_move am
        SET narration = CASE
            WHEN char_length(COALESCE(am.narration, '')) = 0 THEN absl.note
            ELSE am.narration || ' ' || absl.note END
        FROM account_bank_statement_line absl
        WHERE absl.move_id = am.id AND char_length(COALESCE(absl.note, '')) > 0
        """,
    )


def pass_payment_to_journal_entry_narration(env):
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE account_move am
        SET narration = CASE
            WHEN char_length(COALESCE(am.narration, '')) = 0 THEN ap.communication
            ELSE am.narration || ' ' || ap.communication END
        FROM account_payment ap
        WHERE ap.move_id = am.id AND char_length(COALESCE(ap.communication, '')) > 0
        """,
    )


def fill_company_account_cash_basis_base_account_id(env):
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE account_chart_template chart
        SET property_cash_basis_base_account_id = att.cash_basis_base_account_id
        FROM account_tax_template att
        WHERE att.chart_template_id = chart.id
            AND att.cash_basis_base_account_id IS NOT NULL
        """,
    )
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE res_company rc
        SET account_cash_basis_base_account_id = at.cash_basis_base_account_id
        FROM account_tax at
        WHERE at.company_id = rc.id
            AND at.cash_basis_base_account_id IS NOT NULL
        """,
    )


def populate_account_groups(env):
    """Generate the generic account groups for each company. Later code will
    do it for manually created groups.
    """
    companies = env["res.company"].with_context(active_test=False).search([])
    for company in companies.filtered("chart_template_id"):
        company.chart_template_id.generate_account_groups(company)


def unfold_manual_account_groups(env):
    """For manually created groups, we check if such group is used in more than
    one company. If so, we unfold it. We also assure proper company for existing one.
    """

    def _get_all_children(groups):
        children = env["account.group"].search([("parent_id", "in", groups.ids)])
        if children:
            children |= _get_all_children(children)
        return children

    def _get_all_parents(groups):
        parents = groups.mapped("parent_id")
        if parents:
            parents |= _get_all_parents(parents)
        return parents

    AccountGroup = env["account.group"]
    AccountGroup._parent_store_compute()
    env.cr.execute(
        """SELECT ag.id FROM account_group ag
        LEFT JOIN ir_model_data imd
            ON ag.id = imd.res_id AND imd.model = 'account.group'
                AND imd.module != '__export__'
        WHERE imd.id IS NULL"""
    )
    all_groups = AccountGroup.browse([x[0] for x in env.cr.fetchall()])
    all_groups = all_groups | _get_all_parents(all_groups)
    relation_dict = {}
    for group in all_groups.sorted(key="parent_path"):
        subgroups = group | _get_all_children(group)
        accounts = env["account.account"].search([("group_id", "in", subgroups.ids)])
        companies = accounts.mapped("company_id").sorted()
        for i, company in enumerate(companies):
            if company not in relation_dict:
                relation_dict[company] = {}
            if i == 0:
                if group.company_id != company:
                    group.company_id = company.id
                relation_dict[company][group] = group
                continue
            # Done by SQL for avoiding ORM derived problems
            env.cr.execute(
                """INSERT INTO account_group (parent_id, parent_path, name,
                code_prefix_start, code_prefix_end, company_id,
                create_uid, write_uid, create_date, write_date)
            SELECT {parent_id}, parent_path, name, code_prefix_start,
                code_prefix_end, {company_id}, create_uid,
                write_uid, create_date, write_date
            FROM account_group
            WHERE id = {id}
            RETURNING id
            """.format(
                    id=group.id,
                    company_id=company.id,
                    parent_id=group.parent_id
                    and relation_dict[company][group.parent_id].id
                    or "NULL",
                )
            )
            new_group = AccountGroup.browse(env.cr.fetchone())
            relation_dict[company][group] = new_group
    AccountGroup._parent_store_compute()


def _create_fixed_vietnam_bank_accounts(env):
    """Create new accounts in v14"""
    vn_chart_template = env.ref("l10n_vn.vn_template", raise_if_not_found=False)
    if vn_chart_template:
        companies = env["res.company"].search(
            [("chart_template_id", "=", vn_chart_template.id)]
        )
        for company in companies:
            default_account_code = env["account.account"]._search_new_account_code(
                company,
                vn_chart_template.code_digits,
                company.bank_account_code_prefix or "",
            )

            openupgrade.logged_query(
                env.cr,
                """
                UPDATE account_account
                SET code = '{1}', name = '{0}'
                WHERE code = '1121' AND company_id = {2};
                """.format(
                    _("Bank"),
                    default_account_code,
                    company.id,
                ),
            )
            _logger.warning(
                "Account with code '1121' has been changed to"
                " account with code %s on company %s!"
                % (default_account_code, company.name)
            )

            liquidity_account_type = env.ref(
                "account.data_account_type_liquidity", raise_if_not_found=False
            )
            query = """
            INSERT INTO account_account
            ( name, code, user_type_id,
            company_id, internal_type, internal_group, reconcile)
            VALUES
            ('{4}', '1121', {0}, {1}, '{2}', '{3}', false)
            """
            if not env["account.account"].search(
                [("code", "=", "1122"), ("company_id", "=", company.id)]
            ):
                query += ",('{5}', '1122', {0}, {1}, '{2}', '{3}', false)"
            if not env["account.account"].search(
                [("code", "=", "1123"), ("company_id", "=", company.id)]
            ):
                query += ",('{6}', '1123', {0}, {1}, '{2}', '{3}', false)"
            openupgrade.logged_query(
                env.cr,
                query.format(
                    liquidity_account_type.id,
                    company.id,
                    liquidity_account_type.type,
                    liquidity_account_type.internal_group,
                    _("Vietnamese Dong"),
                    _("Foreign currencies"),
                    _("Monetary Gold"),
                ),
            )


def fill_company_account_journal_suspense_account_id(env):
    companies = env["res.company"].search([("chart_template_id", "!=", False)])
    for company in companies:
        chart = company.chart_template_id
        account = chart._create_liquidity_journal_suspense_account(
            company, chart.code_digits
        )
        company.account_journal_suspense_account_id = account
    journals = (
        env["account.journal"]
        .with_context(active_test=False)
        .search([("type", "in", ("bank", "cash")), ("company_id", "in", companies.ids)])
    )
    journals._compute_suspense_account_id()


def fill_statement_lines_with_no_move(env):
    stl_dates = {}
    stl_dates_by_company = {}
    env.cr.execute(
        """
        SELECT id, %s, company_id
        FROM account_bank_statement_line
        WHERE move_id IS NULL"""
        % (openupgrade.get_legacy_name("date"),)
    )
    for stl_id, stl_date, stl_company in env.cr.fetchall():
        stl_dates[stl_id] = stl_date
        if stl_company in stl_dates_by_company:
            stl_dates_by_company[stl_company] = min(
                stl_date, stl_dates_by_company[stl_company]
            )
        else:
            stl_dates_by_company[stl_company] = stl_date
    st_lines = env["account.bank.statement.line"].browse(list(stl_dates.keys()))
    for st_line in st_lines.with_context(
        check_move_validity=False, tracking_disable=True
    ):
        move = env["account.move"].create(
            {
                "name": "/",
                "date": stl_dates[st_line.id],
                "statement_line_id": st_line.id,
                "move_type": "entry",
                "journal_id": st_line.statement_id.journal_id.id,
                "company_id": st_line.statement_id.company_id.id,
                "currency_id": st_line.statement_id.journal_id.currency_id.id
                or st_line.statement_id.company_id.currency_id.id,
            }
        )
        st_line.move_id = move
        deprecated_accounts = env["account.account"].search(
            [("deprecated", "=", True), ("company_id", "=", st_line.company_id.id)]
        )
        deprecated_accounts.deprecated = False
        try:
            st_line._synchronize_to_moves(
                [
                    "payment_ref",
                    "amount",
                    "amount_currency",
                    "foreign_currency_id",
                    "currency_id",
                    "partner_id",
                ]
            )
        except Exception as e:
            _logger.error("Failed for statement line with id %s: %s", st_line.id, e)
            raise
        deprecated_accounts.deprecated = True

    openupgrade.logged_query(
        env.cr,
        """
        UPDATE account_move am
        SET partner_bank_id = absl.bank_account_id
        FROM account_bank_statement_line absl
        WHERE am.statement_line_id = absl.id AND am.partner_bank_id IS NULL
            AND absl.bank_account_id IS NOT NULL""",
    )


def fill_account_journal_payment_credit_debit_account_id(env):
    journals = (
        env["account.journal"]
        .with_context(active_test=False)
        .search([("type", "in", ("bank", "cash"))])
    )
    current_assets_type = env.ref("account.data_account_type_current_assets")
    for journal in journals:
        random_account = env["account.account"].search(
            [("company_id", "=", journal.company_id.id)], limit=1
        )
        digits = len(random_account.code) if random_account else 6
        if journal.type == "bank":
            liquidity_account_prefix = journal.company_id.bank_account_code_prefix or ""
        else:
            liquidity_account_prefix = (
                journal.company_id.cash_account_code_prefix
                or journal.company_id.bank_account_code_prefix
                or ""
            )
        journal.payment_debit_account_id = env["account.account"].create(
            {
                "name": _("Outstanding Receipts"),
                "code": env["account.account"]._search_new_account_code(
                    journal.company_id, digits, liquidity_account_prefix
                ),
                "reconcile": True,
                "user_type_id": current_assets_type.id,
                "company_id": journal.company_id.id,
            }
        )
        journal.payment_credit_account_id = (
            env["account.account"]
            .create(
                {
                    "name": _("Outstanding Payments"),
                    "code": env["account.account"]._search_new_account_code(
                        journal.company_id, digits, liquidity_account_prefix
                    ),
                    "reconcile": True,
                    "user_type_id": current_assets_type.id,
                    "company_id": journal.company_id.id,
                }
            )
            .id
        )


def create_new_counterpar_account_payment_transfer(env):
    # Create new counterpart payment with account payment transfer
    openupgrade.logged_query(
        env.cr,
        """
        INSERT INTO account_payment (move_id, is_internal_transfer, partner_type,
            payment_type,
            amount, currency_id,
            destination_account_id, partner_id, journal_id,
            create_uid, create_date, write_uid, write_date)
        SELECT move.id, true, ap.partner_type,
            CASE
            WHEN journal.id = ap.destination_journal_id THEN 'inbound' ELSE 'outbound'
            END,
            ap.amount, ap.currency_id,
            ap.destination_account_id, ap.partner_id, move.journal_id,
            ap.create_uid, ap.create_date, ap.write_uid, ap.write_date
        FROM account_payment ap
        JOIN account_move move
            ON (move.payment_id = ap.id AND move.id != ap.move_id)
        JOIN account_journal journal ON journal.id = move.journal_id
        WHERE ap.payment_type = 'transfer'
        """,
    )


def map_account_payment_transfer(env):
    # map payment_type from transfer to 'outbound'
    # and set is_internal_transfer as true on account payment transfer
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE account_payment ap
        SET is_internal_transfer = true, payment_type = 'outbound'
        WHERE ap.payment_type = 'transfer'
        """,
    )


def fill_account_payment_with_no_move(env):
    p_data = {}
    p_dates_by_company = {}
    env.cr.execute(
        """
        SELECT ap.id, ap.%s, ap.%s, ap.%s, ap.state, aj.company_id
        FROM account_payment ap
        JOIN account_journal aj ON ap.journal_id = aj.id
        WHERE ap.move_id IS NULL
        """
        % (
            openupgrade.get_legacy_name("journal_id"),
            openupgrade.get_legacy_name("name"),
            openupgrade.get_legacy_name("payment_date"),
        )
    )
    for (
        p_id,
        p_journal_id,
        p_name,
        p_payment_date,
        p_state,
        p_company,
    ) in env.cr.fetchall():
        p_data[p_id] = {
            "journal_id": p_journal_id,
            "name": p_name,
            "state": p_state,
            "payment_date": p_payment_date,
        }
        if p_company in p_dates_by_company:
            p_dates_by_company[p_company] = min(
                p_payment_date, p_dates_by_company[p_company]
            )
        else:
            p_dates_by_company[p_company] = p_payment_date
    payments = env["account.payment"].browse(list(p_data.keys()))
    for payment in payments.with_context(
        check_move_validity=False, tracking_disable=True
    ):
        journal = env["account.journal"].browse(p_data[payment.id]["journal_id"])
        move = env["account.move"].create(
            {
                "name": "/",
                # map old payment's state to move's state:
                # draft -> draft, cancelled -> cancel
                "state": "cancel"
                if p_data[payment.id]["state"] == "cancelled"
                else "draft",
                "date": p_data[payment.id]["payment_date"],
                "payment_id": payment.id,
                "move_type": "entry",
                "journal_id": journal.id,
                "company_id": journal.company_id.id,
                "currency_id": journal.currency_id.id
                or journal.company_id.currency_id.id,
            }
        )
        payment.move_id = move
        deprecated_accounts = env["account.account"].search(
            [("deprecated", "=", True), ("company_id", "=", payment.company_id.id)]
        )
        deprecated_accounts.deprecated = False
        try:
            payment._synchronize_to_moves(
                [
                    "date",
                    "amount",
                    "payment_type",
                    "partner_type",
                    "payment_reference",
                    "is_internal_transfer",
                    "currency_id",
                    "partner_id",
                    "destination_account_id",
                    "partner_bank_id",
                    "journal_id",
                ]
            )
        except Exception as e:
            _logger.error("Failed for payment with id %s: %s", payment.id, e)
            raise
        deprecated_accounts.deprecated = True


def try_delete_noupdate_records(env):
    openupgrade.delete_records_safely_by_xml_id(
        env,
        [
            "account.sequence_payment_customer_invoice",
            "account.sequence_payment_customer_refund",
            "account.sequence_payment_supplier_invoice",
            "account.sequence_payment_supplier_refund",
            "account.sequence_payment_transfer",
        ],
    )


def fill_account_move_line_amounts(env):
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE account_move_line aml
        SET amount_currency = aml.debit-aml.credit
        FROM account_move am
        JOIN res_company rc ON am.company_id = rc.id
        WHERE aml.currency_id = rc.currency_id AND
            aml.move_id = am.id AND
            aml.debit + aml.credit > 0 AND (
                aml.amount_currency = 0 OR aml.amount_currency IS NULL)""",
    )


def fill_account_move_line_date(env):
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE account_move_line aml
        SET date = COALESCE(am.date, aml.create_date::date)
        FROM account_move am
        WHERE aml.move_id = am.id AND aml.date IS NULL""",
    )


def _migrate_currency_exchange_account_company(env):
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE res_company company
        SET
            expense_currency_exchange_account_id = %s,
            income_currency_exchange_account_id = %s
        FROM account_journal aj
        WHERE aj.id = company.currency_exchange_journal_id
        AND aj.company_id = company.id
        """
        % (
            openupgrade.get_legacy_name("default_debit_account_id"),
            openupgrade.get_legacy_name("default_credit_account_id"),
        ),
    )


@openupgrade.migrate()
def migrate(env, version):
    fill_account_journal_posted_before(env)
    fill_code_prefix_end_field(env)
    fill_default_account_id_field(env)
    fill_payment_id_and_statement_line_id_fields(env)
    fill_partial_reconcile_debit_and_credit_amounts(env)
    create_account_reconcile_model_lines(env)
    create_account_reconcile_model_template_lines(env)
    create_account_tax_report_lines(env)
    post_statements_with_unreconciled_lines(env)
    pass_bank_statement_line_note_to_journal_entry_narration(env)
    pass_payment_to_journal_entry_narration(env)
    fill_company_account_cash_basis_base_account_id(env)
    fill_account_move_line_amounts(env)
    fill_account_move_line_date(env)
    openupgrade.load_data(env.cr, "account", "14.0.1.1/noupdate_changes.xml")
    try_delete_noupdate_records(env)
    _create_hooks(env)
    populate_account_groups(env)
    unfold_manual_account_groups(env)
    # Launch a recomputation of the account groups after previous changes
    env["account.account"].search([])._compute_account_group()
    _create_fixed_vietnam_bank_accounts(env)
    fill_company_account_journal_suspense_account_id(env)
    fill_statement_lines_with_no_move(env)
    fill_account_journal_payment_credit_debit_account_id(env)
    create_new_counterpar_account_payment_transfer(env)
    map_account_payment_transfer(env)
    fill_account_payment_with_no_move(env)
    _delete_hooks(env)
    openupgrade.delete_record_translations(
        env.cr,
        "account",
        ["email_template_edi_invoice", "mail_template_data_payment_receipt"],
    )
    _migrate_currency_exchange_account_company(env)
