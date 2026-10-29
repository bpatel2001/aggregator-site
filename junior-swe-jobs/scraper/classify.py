"""Decide whether a job title is a junior software engineering role.

classify(title) returns one of:
  "entry"   - software role with an explicit junior signal (new grad, junior, Engineer I, ...)
  "open"    - software role with no level stated and no senior signal (often junior-friendly)
  "intern"  - software internship / co-op
  None      - not a software role, or clearly senior
"""
import re

# Titles that are software engineering work.
SOFTWARE = re.compile(
    r"""
    \bsoftware\b
    | \bswe\b | \bsde\b
    | \bdevelopers?\b
    | \bprogrammer\b
    | \bfull[\s-]?stack\b
    | \b(front|back)[\s-]?end\s+(engineer|developer)
    | \b(ios|android|mobile|web|cloud|platform|devops|game)\s+(engineer|developer)
    | \bsite\s+reliability
    | \bapplications?\s+(development|developer|engineer)
    | \btechnology\s+(development|leadership\s+development|associate)\s+program
    | \b(tdp|tldp)\b
    | \bengineer(ing)?\s+training\s+program
    | \bamts\b
    """,
    re.I | re.X,
)

# Software-ish words that are not engineering roles.
NOT_SOFTWARE = re.compile(
    r"""
    \bsales\b | \baccount\s+(executive|manager)\b | \brecruit | \bmarketing\b
    | \bbusiness\s+development\b | \bpartner\s+development\b
    | \bproduct\s+(manager|management|owner|marketing)\b | \btechnical\s+writer\b
    | \bsoftware\s+(sales|licens|asset|buyer|procurement|support\s+specialist)
    """,
    re.I | re.X,
)

INTERN = re.compile(r"\bintern(ship)?s?\b|\bco-?op\b", re.I)

# Strong senior signals. These win even over a junior keyword.
SENIOR = re.compile(
    r"""
    \bsenior\b | \bsr\.?\b | \bstaff\b | \bprincipal\b | \blead\b | \bleader\b
    | \bmanager\b | \bmgr\b | \bdirector\b | \bhead\s+of\b | \barchitect\b
    | \bvp\b | \bvice\s+president\b | \bdistinguished\b | \bfellow\b | \bchief\b
    | \bsupervisor\b | \bexpert\b | \bavp\b | \bsvp\b | \bmanaging\b
    | \b[slp]mts\b | \bmts\b | \bexperienced\b | \bintermediate\b | \bmid[\s-]?level\b
    | \bspecialist\s+(iii|iv|3|4)\b
    """,
    re.I | re.X,
)

# Level markers that mean "not junior" unless a junior keyword is also present.
MID_LEVEL = re.compile(
    r"""
    \b(engineer|developer|sde|swe|analyst|programmer)\s*[,-]?\s*(ii|iii|iv|v|2|3|4|5)\b
    | \b(ii|iii|iv)\b
    | \blevel\s*[2-9]\b
    | \beng\s*[2-9]\b
    | \bp[2-9]\b
    | \bc1[1-9]\b
    """,
    re.I | re.X,
)

JUNIOR = re.compile(
    r"""
    \bnew\s+(college\s+)?grad(uate)?s?\b | \bcollege\s+grad(uate)?\b | \bgraduate\b
    | \buniversity\b | \bcampus\b | \bentry[\s-]?level\b | \bjunior\b | \bjr\.?\b
    | \bassociate\s+(software|developer|engineer|sde|swe|application)
    | \b(engineer|developer|sde|swe|programmer)\s*[,-]?\s*(i|1)\b(?!\s*/)
    | (?:,|-|\)|\badvisor)\s*i\s*(?:$|\()
    | \b(engineer|developer|sde|swe|programmer)\s*(i|1)\s*/\s*(ii|2)\b
    | \blevel\s*1\b | \beng\s*1\b | \bp1\b
    | \bearly[\s-]?(career|talent|in\s+career)\b | \brotation(al)?\b
    | \bdevelopment\s+program\b | \btraining\s+program\b | \bapprentice(ship)?\b
    | \bfresher\b | \bamts\b | \b(tdp|tldp)\b
    | \b20(2[5-9]|3[0-1])\s+(start|grad|graduate|cohort)
    """,
    re.I | re.X,
)


def classify(title: str):
    t = " ".join((title or "").split())
    if not t or not SOFTWARE.search(t) or NOT_SOFTWARE.search(t):
        return None
    if SENIOR.search(t):
        return None
    if INTERN.search(t):
        return "intern"
    if JUNIOR.search(t):
        return "entry"
    if MID_LEVEL.search(t):
        return None
    return "open"


# --- location -----------------------------------------------------------

US_STATES = (
    "alabama alaska arizona arkansas california colorado connecticut delaware florida georgia "
    "hawaii idaho illinois indiana iowa kansas kentucky louisiana maine maryland massachusetts "
    "michigan minnesota mississippi missouri montana nebraska nevada new hampshire new jersey "
    "new mexico new york north carolina north dakota ohio oklahoma oregon pennsylvania "
    "rhode island south carolina south dakota tennessee texas utah vermont virginia washington "
    "west virginia wisconsin wyoming district of columbia"
)
_MULTI = [
    "new hampshire", "new jersey", "new mexico", "new york", "north carolina", "north dakota",
    "rhode island", "south carolina", "south dakota", "west virginia", "district of columbia",
]
_STATE_NAMES = _MULTI + [
    w for w in US_STATES.split()
    if w not in {"new", "hampshire", "jersey", "mexico", "york", "north", "carolina", "dakota",
                 "rhode", "island", "south", "west", "district", "of", "columbia"}
]
_STATE_ABBR = (
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ "
    "NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC"
).split()

US_RE = re.compile(
    r"\b(united states|usa|u\.s\.a?\.?|us[\s-]remote|remote[\s-]us|nationwide)\b|\(usa\)|^us\b|\bus-[a-z]{2}\b|"
    + r"\b(" + "|".join(re.escape(s) for s in _STATE_NAMES) + r")\b",
    re.I,
)
US_ABBR_RE = re.compile(r"(?:,|\s-|^)\s*(" + "|".join(_STATE_ABBR) + r")\b")
US_CODE_RE = re.compile(r"(?:^|[\s,(/-])US(?:$|[\s,)/-])")  # bare "US" token, case-sensitive
NON_US_RE = re.compile(
    r"\b(india|bengaluru|bangalore|hyderabad|pune|chennai|gurgaon|gurugram|noida|mumbai|"
    r"canada|toronto|vancouver|montreal|mexico city|guadalajara|brazil|costa rica|argentina|"
    r"colombia|united kingdom|uk\b|london|ireland|dublin|germany|france|poland|krakow|warsaw|"
    r"spain|italy|netherlands|romania|hungary|czech|israel|china|shanghai|beijing|shenzhen|"
    r"taiwan|taipei|japan|tokyo|korea|seoul|singapore|malaysia|kuala lumpur|philippines|manila|"
    r"taguig|vietnam|australia|sydney|melbourne|new zealand|south africa|egypt|kenya)\b",
    re.I,
)


def guess_country(location: str, title: str = "") -> str:
    """Return 'us', 'non-us' or 'unknown'."""
    text = f"{title} || {location or ''}"
    tag = re.match(r"\s*\(([a-z]{2,3})\)", title or "", re.I)  # Walmart style: "(USA) ...", "(IND) ..."
    if tag:
        return "us" if tag.group(1).upper() in ("US", "USA") else "non-us"
    if NON_US_RE.search(text) and not US_RE.search(location or ""):
        return "non-us"
    if US_RE.search(location or "") or US_ABBR_RE.search(location or "") or US_CODE_RE.search(location or ""):
        return "us"
    return "unknown"
