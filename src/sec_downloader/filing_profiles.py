"""Reviewed metric labels, concepts and fiscal periods for the two current filings."""
# Reviewed locations and fiscal durations in the two current cached filings.
PROFILES = {
    "wmt-2025": (50, "104169", "2024-02-01", "2025-01-31", {
        "net_sales": ("Net sales", "RevenueFromContractWithCustomerExcludingAssessedTax"),
        "total_revenues": ("Total revenues", "Revenues"),
        "cost_of_sales": ("Cost of sales", "CostOfRevenue"),
        "operating_income": ("Operating income", "OperatingIncomeLoss"),
        "income_before_income_taxes": ("Income before income taxes", "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"),
        "consolidated_net_income": ("Consolidated net income", "ProfitLoss"),
        "net_income": ("Consolidated net income attributable to Walmart", "NetIncomeLoss"),
    }),
    "aapl-2025": (23, "320193", "2024-09-29", "2025-09-27", {
        "net_sales": ("Total net sales", "RevenueFromContractWithCustomerExcludingAssessedTax"),
        "cost_of_sales": ("Total cost of sales", "CostOfGoodsAndServicesSold"),
        "gross_profit": ("Gross margin", "GrossProfit"),
        "operating_income": ("Operating income", "OperatingIncomeLoss"),
        "net_income": ("Net income", "NetIncomeLoss"),
    }),
}


# Q3 FY2026 reuses Walmart labels/concepts, with a current nine-month anchor.
PROFILES["wmt-2026-q3"] = (None, "104169", "2025-02-01", "2025-10-31", PROFILES["wmt-2025"][4])

from .accounting import AMAZON_METRICS
PROFILES["amzn-2025"] = (None, "1018724", "2025-01-01", "2025-12-31", AMAZON_METRICS)
