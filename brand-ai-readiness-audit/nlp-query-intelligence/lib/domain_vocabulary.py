"""Pluggable domain vocabulary bundles for the ONE shared NLP/evidence
pipeline (nlp_engine.py, evidence_matcher.py, scoring.py,
combination_checker.py). This module is the only thing that changes
between domains — none of the pipeline code branches on domain_type;
it only ever asks "which concept dictionaries apply here" via
get_vocabulary(domain_type) and looks words up in whatever it's handed.

A bundle has exactly the shape vocabulary.py's original ATTRIBUTE_
SYNONYMS/AUDIENCE_TERMS/USE_CASE_TERMS had: {canonical_key: [synonym,
...]}. Adding a fifth domain later means adding one more dict here, not
touching the engine.
"""

SHOPPING = {
    "attributes": {
        "ram": ["ram", "memory"],
        "storage": ["storage", "ssd", "hdd", "rom", "hard drive"],
        "processor": ["processor", "cpu", "chipset", "chip"],
        "display": ["display", "screen", "panel"],
        "battery": ["battery", "battery life"],
        "camera": ["camera", "megapixel", "mp camera"],
        "weight": ["weight", "lightweight"],
        "graphics": ["graphics", "gpu", "graphics card"],
        "resolution": ["resolution"],
        "connectivity": ["connectivity", "wireless", "bluetooth", "wired", "2.4ghz dongle"],
        "backlighting": ["backlighting", "backlit", "rgb lighting", "rgb"],
        "switch_type": ["switch type", "mechanical switches", "membrane switches", "linear switches"],
        "layout": ["layout", "tenkeyless", "full-size layout", "compact layout"],
    },
    "audiences": {
        "students": ["student", "students", "cse student", "cse students",
                     "college student", "college students", "engineering student",
                     "engineering students"],
        "gamers": ["gamer", "gamers", "gaming enthusiast"],
        "professionals": ["professional", "professionals", "working professional",
                           "working professionals"],
        "developers": ["developer", "developers", "programmer", "programmers"],
        "creators": ["creator", "creators", "content creator", "content creators"],
        "business": ["business", "businesses", "enterprise"],
        "beginners": ["beginner", "beginners", "first-time buyer"],
    },
    "use_cases": {
        "programming": ["programming", "coding", "code", "software development",
                        "development", "developer use"],
        "gaming": ["gaming", "games", "game development"],
        "editing": ["editing", "video editing", "photo editing", "content editing"],
        "office": ["office work", "office use", "productivity"],
        "browsing": ["browsing", "everyday use", "casual use", "web browsing"],
        "design": ["design", "graphic design", "ui design"],
        "data science": ["data science", "machine learning", "data analysis"],
    },
}

EDUCATION = {
    "attributes": {
        "tuition": ["tuition", "tuition fee", "tuition fees", "course fee", "program fee"],
        "duration": ["duration", "program length", "credit hours", "years to complete"],
        "accreditation": ["accredited", "accreditation", "accrediting body"],
        "class_size": ["class size", "student-faculty ratio", "student to faculty ratio"],
        "financial_aid": ["financial aid", "scholarship", "scholarships", "grants", "student loans"],
        "delivery_mode": ["online program", "on-campus", "hybrid program", "distance learning"],
        "admission_requirements": ["admission requirements", "entry requirements", "eligibility criteria"],
    },
    "audiences": {
        "undergraduate students": ["undergraduate", "undergraduate student", "undergraduate students",
                                    "bachelor's student"],
        "graduate students": ["graduate student", "graduate students", "postgraduate", "master's student",
                               "phd student"],
        "international students": ["international student", "international students", "overseas student"],
        "working professionals": ["working professional", "working professionals", "part-time student"],
        "parents": ["parent", "parents", "guardian", "guardians"],
        "transfer students": ["transfer student", "transfer students"],
        "high school students": ["high school student", "high school students", "prospective student",
                                  "prospective students"],
    },
    "use_cases": {
        "research": ["research", "research opportunities", "research program"],
        "career advancement": ["career advancement", "career growth", "job placement", "career services"],
        "skill development": ["skill development", "hands-on learning", "practical training"],
        "certification": ["certification", "certificate program", "professional certification"],
        "distance learning": ["distance learning", "remote learning", "online learning"],
    },
}

HEALTHCARE = {
    "attributes": {
        "insurance_accepted": ["insurance", "accepts insurance", "in-network", "insurance accepted",
                                "insurance plans accepted"],
        "appointment_availability": ["appointment", "same-day appointment", "walk-in", "book an appointment",
                                      "schedule an appointment"],
        "specialty": ["specialist", "specialty", "specialization", "board-certified"],
        "telehealth": ["telehealth", "virtual visit", "online consultation", "video consultation"],
        "cost": ["out-of-pocket", "copay", "co-pay", "self-pay", "consultation fee"],
        "accreditation": ["accredited", "accreditation", "certified"],
    },
    "audiences": {
        "patients": ["patient", "patients", "new patient", "new patients", "existing patient",
                     "existing patients"],
        "caregivers": ["caregiver", "caregivers", "family member", "family members"],
        "seniors": ["senior", "seniors", "elderly", "geriatric"],
        "children": ["child", "children", "pediatric patient", "pediatric patients", "kids"],
        "pregnant patients": ["pregnant", "maternity", "prenatal", "expectant mother"],
    },
    "use_cases": {
        "routine checkup": ["routine checkup", "annual checkup", "wellness visit", "physical exam"],
        "emergency care": ["emergency care", "urgent care", "emergency room", "er visit"],
        "specialist consultation": ["specialist consultation", "referral", "second opinion"],
        "preventive care": ["preventive care", "screening", "vaccination", "immunization"],
        "chronic condition management": ["chronic condition", "ongoing treatment", "disease management"],
    },
}

# Deliberately small and cross-domain-safe: a site that isn't shopping,
# education or healthcare gets audience/use-case concepts general enough
# to be honest anywhere, and NO attribute guesses at all -- inventing
# "attributes" for an unknown domain would be exactly the kind of
# unfounded assumption the rest of this subsystem refuses to make. A
# generic-domain query about a specific attribute correctly surfaces as
# an unrecognized_term rather than a guessed match.
GENERIC = {
    "attributes": {},
    "audiences": {
        "customers": ["customer", "customers", "client", "clients"],
        "professionals": ["professional", "professionals"],
        "beginners": ["beginner", "beginners", "newcomer", "newcomers"],
    },
    "use_cases": {
        "general use": ["general use", "everyday use"],
        "professional use": ["professional use", "business use"],
        "personal use": ["personal use", "individual use"],
    },
}

_BY_DOMAIN_TYPE = {
    "shopping": SHOPPING,
    "education": EDUCATION,
    "healthcare": HEALTHCARE,
}

ALL_DOMAINS = [SHOPPING, EDUCATION, HEALTHCARE, GENERIC]


def get_vocabulary(domain_type):
    """The single resolution point: every caller in the pipeline that used
    to reach into vocabulary.ATTRIBUTE_SYNONYMS/AUDIENCE_TERMS/USE_CASE_TERMS
    directly now calls this instead, keyed off profile["domain_type"]."""
    return _BY_DOMAIN_TYPE.get(domain_type, GENERIC)


def concept_words_for(domain_type):
    """Every single word appearing in THIS domain's own attribute/
    audience/use-case synonyms -- used by entity_schema.py to exclude
    concept words from entity candidacy (a qualifier-adjacent word like
    "tuition" should never masquerade as a program name).

    Deliberately scoped to ONE domain rather than the union of all four:
    an early version used a global union and it broke entity discovery on
    non-shopping sites -- "business" is a SHOPPING audience word (via
    "businesses"/"enterprise"), so a cross-domain union silently deleted
    "Business Administration" as a candidate program name on an
    EDUCATION site, and "science" (from shopping's "data science" use
    case) did the same to "Computer Science". A word only means something
    as a concept within the domain that claims it; excluding it
    everywhere was collateral damage from a different site's vocabulary."""
    bundle = get_vocabulary(domain_type)
    words = set()
    for term_map in bundle.values():
        for synonyms in term_map.values():
            for phrase in synonyms:
                words.update(phrase.split())
    return words
