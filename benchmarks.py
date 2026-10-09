"""Sektor üzrə orta Debt/EBITDA (Damodaran, ABŞ, 2026-cı il yanvar məlumatı).
Mənbə: https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/dbtfund.html
Maliyyə sektorları (bank, broker, sığorta-olmayan maliyyə) və mənfi/NA dəyərlər çıxarılıb:
orada Debt/EBITDA mənalı leverage limiti deyil."""

DEFAULT_SECTOR = "Total Market (without financials)"

SECTORS = {
    "Advertising": 4.70, "Aerospace/Defense": 4.62, "Air Transport": 5.13, "Apparel": 3.47,
    "Auto & Truck": 8.79, "Auto Parts": 2.95, "Beverage (Alcoholic)": 2.57, "Beverage (Soft)": 3.23,
    "Broadcasting": 3.90, "Building Materials": 2.52, "Business & Consumer Services": 2.77,
    "Cable TV": 3.89, "Chemical (Basic)": 3.75, "Chemical (Diversified)": 6.15,
    "Chemical (Specialty)": 3.52, "Coal & Related Energy": 1.51, "Computer Services": 3.47,
    "Computers/Peripherals": 1.17, "Construction Supplies": 2.56, "Diversified": 1.42,
    "Drugs (Biotechnology)": 6.20, "Drugs (Pharmaceutical)": 2.43, "Education": 2.57,
    "Electrical Equipment": 3.88, "Electronics (General)": 2.69, "Engineering/Construction": 2.78,
    "Entertainment": 3.46, "Environmental & Waste Services": 3.15, "Farming/Agriculture": 5.92,
    "Food Processing": 3.01, "Food Wholesalers": 3.98, "Furn/Home Furnishings": 4.24,
    "Green & Renewable Energy": 7.28, "Healthcare Products": 2.74, "Healthcare Support Services": 3.35,
    "Healthcare Information and Technology": 3.61, "Homebuilding": 1.61,
    "Hospitals/Healthcare Facilities": 4.10, "Hotel/Gaming": 5.30, "Household Products": 2.17,
    "Information Services": 3.27, "Insurance (General)": 3.84, "Insurance (Life)": 5.62,
    "Insurance (Prop/Cas.)": 1.37, "Machinery": 2.30, "Metals & Mining": 1.43,
    "Office Equipment & Services": 3.44, "Oil/Gas (Integrated)": 1.01,
    "Oil/Gas (Production and Exploration)": 1.74, "Oil/Gas Distribution": 4.97,
    "Oilfield Svcs/Equip.": 2.75, "Packaging & Container": 3.97, "Paper/Forest Products": 2.26,
    "Power": 5.74, "Precious Metals": 1.23, "Publishing & Newspapers": 2.67, "R.E.I.T.": 11.35,
    "Real Estate (Development)": 7.24, "Real Estate (General/Diversified)": 9.50,
    "Real Estate (Operations & Services)": 7.69, "Recreation": 4.78, "Reinsurance": 4.37,
    "Restaurant/Dining": 4.67, "Retail (Automotive)": 5.59, "Retail (Building Supply)": 3.03,
    "Retail (Distributors)": 3.76, "Retail (General)": 1.58, "Retail (Grocery and Food)": 3.27,
    "Retail (REITs)": 6.56, "Retail (Special Lines)": 2.88, "Rubber& Tires": 5.67,
    "Semiconductor": 1.09, "Semiconductor Equip": 1.25, "Shipbuilding & Marine": 1.61, "Shoe": 1.96,
    "Software (Entertainment)": 0.53, "Software (Internet)": 11.32,
    "Software (System & Application)": 1.71, "Steel": 2.20, "Telecom (Wireless)": 3.72,
    "Telecom. Equipment": 2.36, "Telecom. Services": 3.85, "Tobacco": 2.88, "Transportation": 4.70,
    "Transportation (Railroads)": 2.97, "Trucking": 2.30, "Utility (General)": 6.77,
    "Utility (Water)": 6.04,
    DEFAULT_SECTOR: 3.01,
}


def find_sectors(query: str, limit: int = 8):
    """Ada görə axtarış (böyük/kiçik hərf və durğu işarələrinə həssas deyil)."""
    norm = lambda s: "".join(ch for ch in s.lower() if ch.isalnum() or ch == " ").strip()
    q = norm(query)
    if not q:
        return []
    hits = [(n, v) for n, v in SECTORS.items() if q in norm(n)]
    if not hits:  # söz-söz uyğunluq
        words = q.split()
        hits = [(n, v) for n, v in SECTORS.items() if all(w in norm(n) for w in words)]
    return [{"name": n, "debt_to_ebitda": v} for n, v in hits[:limit]]
