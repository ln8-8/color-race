"""All countries for the Flag Factory: (ISO-2 code, short label, display name). No dependencies."""

_ALL = """AF Afghanistan|AL Albania|DZ Algeria|AD Andorra|AO Angola|AG Antigua & Barbuda|AR Argentina|AM Armenia|AU Australia|AT Austria|
AZ Azerbaijan|BS Bahamas|BH Bahrain|BD Bangladesh|BB Barbados|BY Belarus|BE Belgium|BZ Belize|BJ Benin|BT Bhutan|BO Bolivia|
BA Bosnia|BW Botswana|BR Brazil|BN Brunei|BG Bulgaria|BF Burkina Faso|BI Burundi|CV Cabo Verde|KH Cambodia|CM Cameroon|CA Canada|
CF Central African Rep.|TD Chad|CL Chile|CN China|CO Colombia|KM Comoros|CG Congo|CD DR Congo|CR Costa Rica|CI Ivory Coast|HR Croatia|
CU Cuba|CY Cyprus|CZ Czechia|DK Denmark|DJ Djibouti|DM Dominica|DO Dominican Rep.|EC Ecuador|EG Egypt|SV El Salvador|
GQ Equatorial Guinea|ER Eritrea|EE Estonia|SZ Eswatini|ET Ethiopia|FJ Fiji|FI Finland|FR France|GA Gabon|GM Gambia|GE Georgia|
DE Germany|GH Ghana|GR Greece|GD Grenada|GT Guatemala|GN Guinea|GW Guinea-Bissau|GY Guyana|HT Haiti|HN Honduras|HU Hungary|
IS Iceland|IN India|ID Indonesia|IR Iran|IQ Iraq|IE Ireland|IL Israel|IT Italy|JM Jamaica|JP Japan|JO Jordan|KZ Kazakhstan|KE Kenya|
KI Kiribati|XK Kosovo|KW Kuwait|KG Kyrgyzstan|LA Laos|LV Latvia|LB Lebanon|LS Lesotho|LR Liberia|LY Libya|LI Liechtenstein|
LT Lithuania|LU Luxembourg|MG Madagascar|MW Malawi|MY Malaysia|MV Maldives|ML Mali|MT Malta|MH Marshall Islands|MR Mauritania|
MU Mauritius|MX Mexico|FM Micronesia|MD Moldova|MC Monaco|MN Mongolia|ME Montenegro|MA Morocco|MZ Mozambique|MM Myanmar|NA Namibia|
NR Nauru|NP Nepal|NL Netherlands|NZ New Zealand|NI Nicaragua|NE Niger|NG Nigeria|KP North Korea|MK North Macedonia|NO Norway|OM Oman|
PK Pakistan|PW Palau|PS Palestine|PA Panama|PG Papua New Guinea|PY Paraguay|PE Peru|PH Philippines|PL Poland|PT Portugal|QA Qatar|
RO Romania|RU Russia|RW Rwanda|KN Saint Kitts & Nevis|LC Saint Lucia|VC Saint Vincent|WS Samoa|SM San Marino|ST Sao Tome|
SA Saudi Arabia|SN Senegal|RS Serbia|SC Seychelles|SL Sierra Leone|SG Singapore|SK Slovakia|SI Slovenia|SB Solomon Islands|SO Somalia|
ZA South Africa|KR South Korea|SS South Sudan|ES Spain|LK Sri Lanka|SD Sudan|SR Suriname|SE Sweden|CH Switzerland|SY Syria|TW Taiwan|
TJ Tajikistan|TZ Tanzania|TH Thailand|TL Timor-Leste|TG Togo|TO Tonga|TT Trinidad & Tobago|TN Tunisia|TR Turkey|TM Turkmenistan|
TV Tuvalu|UG Uganda|UA Ukraine|AE UAE|GB UK|US USA|UY Uruguay|UZ Uzbekistan|VU Vanuatu|VA Vatican|VE Venezuela|VN Vietnam|YE Yemen|
ZM Zambia|ZW Zimbabwe"""

_LABELS = {"US": "USA", "GB": "UK", "CA": "CAN", "MX": "MEX", "BR": "BRA", "AR": "ARG", "CL": "CHI", "DE": "GER", "NL": "NED",
           "CH": "SUI", "DK": "DEN", "PT": "POR", "HR": "CRO", "RS": "SRB", "SI": "SLO", "GR": "GRE", "BG": "BUL", "LV": "LAT",
           "MD": "MDA", "DZ": "ALG", "NG": "NGA", "ZA": "RSA", "SA": "KSA", "AE": "UAE", "IN": "IND", "BD": "BAN", "LK": "SRI",
           "NP": "NEP", "CN": "CHN", "JP": "JPN", "KR": "KOR", "KP": "PRK", "MN": "MGL", "TW": "TPE", "VN": "VIE", "MY": "MAS",
           "SG": "SGP", "ID": "INA", "PH": "PHI", "NZ": "NZL", "IE": "IRL", "IS": "ISL", "CR": "CRC", "GT": "GUA", "DO": "DOM",
           "UY": "URU", "PY": "PAR", "CI": "CIV", "CD": "COD", "CG": "CGO", "TZ": "TAN", "AO": "ANG", "IR": "IRN", "IQ": "IRQ",
           "KZ": "KAZ", "MA": "MAR", "SE": "SWE", "AT": "AUT", "MT": "MLT", "SK": "SVK", "SV": "SLV", "GQ": "GEQ", "GW": "GBS"}

COUNTRIES = []
for item in _ALL.replace("\n", "").split("|"):
    cc, name = item.split(" ", 1)
    COUNTRIES.append((cc, _LABELS.get(cc, name.replace(" ", "")[:3].upper()), name.upper()))
