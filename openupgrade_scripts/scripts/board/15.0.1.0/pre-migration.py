import ast
import re

from lxml import etree
from openupgradelib import openupgrade


def _delete_context_on_dashboard(env, keys):
    regex_keys_match = [re.compile("%s" % key) for key in keys]
    dashboard_view_data = env["ir.ui.view.custom"].search([])
    for r in dashboard_view_data:
        parsed_arch = etree.XML(r.arch)
        act_window_ids = parsed_arch.xpath("//action/@name")
        actions = env["ir.actions.act_window"].search([("id", "in", act_window_ids)])
        for action in actions:
            condition_for_element = "//action[@name='{}']".format(action.id)
            condition_for_context = "//action[@name='{}']/@context".format(action.id)
            arch_element = parsed_arch.xpath(condition_for_element)
            for index in range(len(arch_element)):
                arch_context = arch_element[index].xpath(condition_for_context)[index]
                arch_context = {
                    k: v
                    for k, v in ast.literal_eval(str(arch_context)).items()
                    if not any(re.fullmatch(regex, k) for regex in regex_keys_match)
                }
                arch_element[index].set("context", str(arch_context))
            new_arch = etree.tostring(parsed_arch, encoding="unicode")
            r.write({"arch": new_arch})


@openupgrade.migrate()
def migrate(env, version):
    _delete_context_on_dashboard(env, ["allowed_company_ids"])
