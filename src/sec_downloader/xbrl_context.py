from copy import deepcopy
from bs4 import BeautifulSoup


def dimensional_context(context):
    """Canonicalize dimension order, retaining unknown/typed content conservatively."""
    result = deepcopy(context)
    dimensions = []
    for raw in result.get("dimensions", []):
        tag = BeautifulSoup(raw, "html.parser")
        members = tag.find_all("xbrldi:explicitmember")
        if not members or tag.find("xbrldi:typedmember"):
            dimensions.append(("unsupported", raw))
        for member in members:
            dimensions.append((member.get("dimension"), member.get_text(strip=True)))
            member.decompose()
        if tag.get_text(strip=True):
            dimensions.append(("unsupported-content", str(tag)))
    result["dimensions"] = sorted(dimensions)
    return result

