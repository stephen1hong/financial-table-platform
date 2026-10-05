"""Reviewed accounting mappings and layout metadata; no table indexes or amounts."""

AMAZON_METRICS = {
    "net_product_sales": ("Net product sales", "RevenueFromContractWithCustomerExcludingAssessedTax"),
    "net_service_sales": ("Net service sales", "RevenueFromContractWithCustomerExcludingAssessedTax"),
    "net_sales": ("Total net sales", "RevenueFromContractWithCustomerExcludingAssessedTax"),
    "cost_of_sales": ("Cost of sales", "CostOfGoodsAndServicesSold"),
    "fulfillment": ("Fulfillment", "amzn:FulfillmentExpense"),
    "technology_infrastructure": ("Technology and infrastructure", "amzn:TechnologyAndInfrastructureExpense"),
    "sales_marketing": ("Sales and marketing", "MarketingExpense"),
    "general_administrative": ("General and administrative", "GeneralAndAdministrativeExpense"),
    "other_operating_expense": ("Other operating expense (income), net", "OtherOperatingIncomeExpenseNet"),
    "total_operating_expenses": ("Total operating expenses", "CostsAndExpenses"),
    "operating_income": ("Operating income", "OperatingIncomeLoss"),
    "nonoperating_income": ("Total non-operating income", "NonoperatingIncomeExpense"),
    "pretax_income": ("Income before income taxes", "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"),
    "income_tax_provision": ("Provision for income taxes", "IncomeTaxExpenseBenefit"),
    "equity_method_activity": ("Equity-method investment activity, net of tax", "IncomeLossFromEquityMethodInvestments"),
    "net_income": ("Net income", "NetIncomeLoss"),
}

STATEMENT_ANCHORS = {"amzn-2025": ("net_sales", "total_operating_expenses", "operating_income", "net_income")}
CALENDARS = {"Amazon": {"header": "Year Ended December 31,", "start_month_day": "01-01", "end_month_day": "12-31"}}
METRIC_DIMENSIONS = {"amzn-2025": {
    "net_product_sales": [("srt:ProductOrServiceAxis", "us-gaap:ProductMember")],
    "net_service_sales": [("srt:ProductOrServiceAxis", "us-gaap:ServiceMember")],
}}
GROSS_PROFIT_NOTES = {"Amazon": (
    "Calculated net sales less the reported cost-of-sales category only; not an Amazon-reported subtotal. "
    "Does not deduct fulfillment, technology and infrastructure, sales and marketing, general and administrative, "
    "or other operating expense. Cost of sales is already included in total operating expenses; "
    "operating income is net sales minus total operating expenses, without a second cost-of-sales deduction."
)}

AMAZON_SEGMENTS = {
    "document_id": "amzn-2025", "entity": "1018724",
    "segments": {"North America": "amzn:NorthAmericaSegmentMember", "International": "amzn:InternationalSegmentMember",
                 "AWS": "amzn:AmazonWebServicesSegmentMember", "Consolidated": None},
    "required_content": ["North America", "International", "AWS", "Operating expenses", "Net income"],
    "heading_pattern": r"^Note\s+\d+.*SEGMENT INFORMATION",
    "unit_evidence": "(in millions)",
    "mappings": {
        "Net sales": ("net_sales", "RevenueFromContractWithCustomerExcludingAssessedTax"),
        "Operating expenses": ("total_operating_expenses", "CostsAndExpenses"),
        "Operating income": ("operating_income", "OperatingIncomeLoss"),
        "Operating income (loss)": ("operating_income", "OperatingIncomeLoss"),
        **{label: (metric, concept) for metric, (label, concept) in AMAZON_METRICS.items()
           if metric in ("nonoperating_income", "income_tax_provision", "equity_method_activity", "net_income")},
    },
    "summed_metrics": ["net_sales", "total_operating_expenses", "operating_income"],
    "expense_components": ["cost_of_sales", "fulfillment", "technology_infrastructure", "sales_marketing", "general_administrative", "other_operating_expense"],
    "bridge": [("operating_income", 1), ("nonoperating_income", 1), ("income_tax_provision", 1), ("equity_method_activity", 1)],
    "bridge_target": "net_income",
    "calculation_policy": "Only operating margin is supported for segments; no separate segment cost-of-sales category is disclosed.",
}


def qname(concept):
    return concept if ":" in concept else "us-gaap:" + concept


METRIC_PARENTS = {"Amazon": {metric: "Operating expenses:" for metric in AMAZON_SEGMENTS["expense_components"]}}
