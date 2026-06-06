"""Tests for the Voter ID (EPIC) extractor (core/voter_id_extractor.py)."""

from core.ocr_engine import TextRegion
from core.voter_id_extractor import VoterIdFields, extract_voter_id


def _bbox(x1, y1, x2, y2):
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def _r(text, x1, y1, x2, y2, conf=0.95):
    return TextRegion(text=text, bbox=_bbox(x1, y1, x2, y2), confidence=conf)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _voter_regions():
    """Standard new-style card: Elector's Name + Father's Name + DOB, value-right."""
    return [
        _r("ELECTION COMMISSION OF INDIA", 40, 20, 460, 50),
        _r("ABC1234567", 360, 60, 560, 90),
        _r("Elector's Name :", 40, 110, 260, 135),
        _r("DEEPAK MEHTA", 280, 110, 500, 135),
        _r("Father's Name :", 40, 150, 260, 175),
        _r("SURESH MEHTA", 280, 150, 500, 175),
        _r("Sex :", 40, 190, 110, 215),
        _r("Male", 130, 190, 230, 215),
        _r("Date of Birth :", 40, 230, 230, 255),
        _r("21/12/1990", 250, 230, 420, 255),
    ]


# ---------------------------------------------------------------------------
# EPIC + names + gender + DOB on the standard card
# ---------------------------------------------------------------------------

class TestVoterIdStandardCard:
    def test_epic_and_names(self):
        f = extract_voter_id(_voter_regions())
        assert f.epic_number == "ABC1234567"
        assert f.name == "DEEPAK MEHTA"
        assert f.relation_name == "SURESH MEHTA"
        assert f.relation_type == "father"

    def test_gender_and_dob(self):
        f = extract_voter_id(_voter_regions())
        assert f.gender == "MALE"
        assert f.date_of_birth == "21/12/1990"
        assert f.age is None

    def test_returns_dataclass(self):
        assert isinstance(extract_voter_id(_voter_regions()), VoterIdFields)


# ---------------------------------------------------------------------------
# Name vs relation disambiguation
# ---------------------------------------------------------------------------

class TestNameRelationDisambiguation:
    def test_bare_name_label_does_not_collapse_into_relation(self):
        """A bare 'Name' label for the holder must not absorb the relation."""
        regions = [
            _r("ABC1234567", 360, 60, 560, 90),
            _r("Name", 40, 110, 160, 135),
            _r("ANITA SHARMA", 200, 110, 420, 135),
            _r("Father's Name", 40, 150, 280, 175),
            _r("RAJESH SHARMA", 300, 150, 520, 175),
        ]
        f = extract_voter_id(regions)
        assert f.name == "ANITA SHARMA"
        assert f.relation_name == "RAJESH SHARMA"
        assert f.relation_type == "father"

    def test_name_not_taken_from_relation_when_no_holder_label(self):
        """If only a relation label exists, holder name stays None (not the relation)."""
        regions = [
            _r("ABC1234567", 360, 60, 560, 90),
            _r("Father's Name", 40, 150, 280, 175),
            _r("RAJESH SHARMA", 300, 150, 520, 175),
        ]
        f = extract_voter_id(regions)
        assert f.relation_name == "RAJESH SHARMA"
        assert f.name is None

    def test_electors_name_wins_over_relation_name_label(self):
        regions = [
            _r("Elector's Name", 40, 110, 280, 135),
            _r("PRIYA NAIR", 300, 110, 500, 135),
            _r("Mother's Name", 40, 150, 280, 175),
            _r("LATA NAIR", 300, 150, 500, 175),
        ]
        f = extract_voter_id(regions)
        assert f.name == "PRIYA NAIR"
        assert f.relation_name == "LATA NAIR"
        assert f.relation_type == "mother"


# ---------------------------------------------------------------------------
# Husband / mother relation variants
# ---------------------------------------------------------------------------

class TestRelationVariants:
    def test_husband_relation(self):
        regions = [
            _r("ABC9876543", 360, 60, 560, 90),
            _r("Elector's Name :", 40, 110, 260, 135),
            _r("SUNITA DEVI", 280, 110, 500, 135),
            _r("Husband's Name :", 40, 150, 300, 175),
            _r("MOHAN LAL", 320, 150, 520, 175),
            _r("Sex :", 40, 190, 110, 215),
            _r("Female", 130, 190, 250, 215),
        ]
        f = extract_voter_id(regions)
        assert f.name == "SUNITA DEVI"
        assert f.relation_name == "MOHAN LAL"
        assert f.relation_type == "husband"
        assert f.gender == "FEMALE"

    def test_name_of_father_phrasing(self):
        regions = [
            _r("Name", 40, 110, 160, 135),
            _r("VIKRAM SINGH", 200, 110, 420, 135),
            _r("Name of Father", 40, 150, 300, 175),
            _r("BALWANT SINGH", 320, 150, 540, 175),
        ]
        f = extract_voter_id(regions)
        assert f.name == "VIKRAM SINGH"
        assert f.relation_name == "BALWANT SINGH"
        assert f.relation_type == "father"


# ---------------------------------------------------------------------------
# Value-below layout (old laminated card)
# ---------------------------------------------------------------------------

class TestValueBelowLayout:
    def test_value_below_label(self):
        regions = [
            _r("ABC1112223", 360, 40, 560, 70),
            _r("Elector's Name", 40, 100, 280, 125),
            _r("ARJUN KUMAR", 44, 130, 280, 158),
            _r("Father's Name", 40, 180, 280, 205),
            _r("DINESH KUMAR", 44, 210, 280, 238),
            _r("Date of Birth", 40, 260, 280, 285),
            _r("05/06/1985", 44, 290, 220, 318),
        ]
        f = extract_voter_id(regions)
        assert f.name == "ARJUN KUMAR"
        assert f.relation_name == "DINESH KUMAR"
        assert f.relation_type == "father"
        assert f.date_of_birth == "05/06/1985"


# ---------------------------------------------------------------------------
# Gender normalisation, incl. Hindi
# ---------------------------------------------------------------------------

class TestGender:
    def test_hindi_male_value_with_english_label(self):
        regions = [
            _r("Sex :", 40, 190, 110, 215),
            _r("पुरुष", 130, 190, 250, 215),
        ]
        f = extract_voter_id(regions)
        assert f.gender == "MALE"

    def test_hindi_female_value_with_english_label(self):
        regions = [
            _r("Gender :", 40, 190, 150, 215),
            _r("महिला", 170, 190, 290, 215),
        ]
        f = extract_voter_id(regions)
        assert f.gender == "FEMALE"

    def test_hindi_only_label_gender_scanned(self):
        """Hindi-only 'लिंग' label is invisible to English matching; value scanned."""
        regions = [
            _r("लिंग", 40, 190, 110, 215),
            _r("महिला", 130, 190, 250, 215),
        ]
        f = extract_voter_id(regions)
        assert f.gender == "FEMALE"

    def test_bare_single_letter_gender_code(self):
        regions = [
            _r("Sex", 40, 190, 110, 215),
            _r("F", 130, 190, 170, 215),
        ]
        f = extract_voter_id(regions)
        assert f.gender == "FEMALE"

    def test_full_word_male(self):
        regions = [
            _r("Sex :", 40, 190, 110, 215),
            _r("MALE", 130, 190, 250, 215),
        ]
        assert extract_voter_id(regions).gender == "MALE"


# ---------------------------------------------------------------------------
# Age fallback
# ---------------------------------------------------------------------------

class TestAgeFallback:
    def test_age_inline_with_label(self):
        regions = [
            _r("ELECTION COMMISSION OF INDIA", 40, 20, 460, 50),
            _r("ABC7654321", 360, 60, 560, 90),
            _r("Elector's Name :", 40, 110, 260, 135),
            _r("MEENA RAO", 280, 110, 480, 135),
            _r("Age : 34", 40, 190, 200, 215),
        ]
        f = extract_voter_id(regions)
        assert f.epic_number == "ABC7654321"
        assert f.age == "34"
        assert f.date_of_birth is None

    def test_age_as_on_does_not_pick_up_year(self):
        """'Age as on 1.1.2024 : 34' must yield 34, not 2024/1."""
        regions = [
            _r("ABC7654321", 360, 60, 560, 90),
            _r("Age as on 1.1.2024 :", 40, 190, 320, 215),
            _r("34", 340, 190, 380, 215),
        ]
        f = extract_voter_id(regions)
        assert f.age == "34"
        assert f.date_of_birth is None

    def test_age_as_on_inline_value(self):
        regions = [
            _r("ABC7654321", 360, 60, 560, 90),
            _r("Age as on 1.1.2024 : 29", 40, 190, 380, 215),
        ]
        f = extract_voter_id(regions)
        assert f.age == "29"
        assert f.date_of_birth is None

    def test_dob_preferred_over_age_when_both_present(self):
        regions = [
            _r("Date of Birth :", 40, 230, 230, 255),
            _r("21/12/1990", 250, 230, 420, 255),
            _r("Age : 35", 40, 270, 200, 295),
        ]
        f = extract_voter_id(regions)
        assert f.date_of_birth == "21/12/1990"
        assert f.age is None


# ---------------------------------------------------------------------------
# EPIC extraction from noisy text
# ---------------------------------------------------------------------------

class TestEpicExtraction:
    def test_epic_from_noisy_region(self):
        regions = [
            _r("IDENTITY CARD NO. ABC 123 4567", 40, 60, 560, 90),
            _r("Elector's Name :", 40, 110, 260, 135),
            _r("RAVI VERMA", 280, 110, 480, 135),
        ]
        f = extract_voter_id(regions)
        assert f.epic_number == "ABC1234567"

    def test_epic_with_spaces_and_punctuation(self):
        regions = [
            _r("No : WXY-987-6543", 40, 60, 560, 90),
        ]
        f = extract_voter_id(regions)
        assert f.epic_number == "WXY9876543"

    def test_no_epic_present(self):
        regions = [
            _r("Elector's Name :", 40, 110, 260, 135),
            _r("RAVI VERMA", 280, 110, 480, 135),
        ]
        f = extract_voter_id(regions)
        assert f.epic_number is None


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_regions(self):
        f = extract_voter_id([])
        assert f.epic_number is None
        assert f.name is None
        assert f.relation_name is None
        assert f.relation_type is None
        assert f.gender is None
        assert f.date_of_birth is None
        assert f.age is None

    def test_blank_text_regions(self):
        regions = [_r("", 0, 0, 10, 10), _r("   ", 0, 20, 10, 30)]
        f = extract_voter_id(regions)
        assert f.epic_number is None
        assert f.name is None

    def test_colon_prefixed_value_is_cleaned(self):
        """Some OCR runs glue the label onto the value region."""
        regions = [
            _r("Name", 40, 110, 160, 135),
            _r(": KIRAN BEDI", 200, 110, 460, 135),
        ]
        f = extract_voter_id(regions)
        assert f.name == "KIRAN BEDI"

    def test_full_card_with_all_fields(self):
        regions = [
            _r("ELECTION COMMISSION OF INDIA", 40, 20, 460, 50),
            _r("Elector Photo Identity Card", 40, 55, 460, 80),
            _r("ABC1234567", 360, 85, 560, 115),
            _r("Elector's Name :", 40, 130, 260, 155),
            _r("DEEPAK MEHTA", 280, 130, 500, 155),
            _r("Father's Name :", 40, 170, 260, 195),
            _r("SURESH MEHTA", 280, 170, 500, 195),
            _r("Sex :", 40, 210, 110, 235),
            _r("पुरुष", 130, 210, 250, 235),
            _r("Date of Birth :", 40, 250, 230, 275),
            _r("21/12/1990", 250, 250, 420, 275),
        ]
        f = extract_voter_id(regions)
        assert f.epic_number == "ABC1234567"
        assert f.name == "DEEPAK MEHTA"
        assert f.relation_name == "SURESH MEHTA"
        assert f.relation_type == "father"
        assert f.gender == "MALE"
        assert f.date_of_birth == "21/12/1990"
        assert f.age is None
