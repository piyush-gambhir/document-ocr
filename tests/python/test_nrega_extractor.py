"""Deterministic synthetic-region tests for the NREGA job-card extractor."""

from core.nrega_extractor import NregaFields, NregaMember, extract_nrega
from core.ocr_engine import TextRegion


def _bbox(x1, y1, x2, y2):
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def _r(text, x1, y1, x2, y2, conf=0.95):
    return TextRegion(text=text, bbox=_bbox(x1, y1, x2, y2), confidence=conf)


def _english_job_card():
    """Annexure-5-style English card with a two-member table."""
    return [
        _r("MAHATMA GANDHI NREGA", 20, 10, 370, 40),
        _r("Job Card No.", 20, 60, 170, 86),
        _r("RJ-27-001-002-0008147/00", 190, 60, 510, 86),
        _r("Validity Period: 01/04/2019 to 31/03/2024", 20, 98, 500, 126),
        _r("Name of Head of Household", 20, 145, 280, 171),
        _r("SITA DEVI", 310, 145, 460, 171),
        _r("Category", 20, 180, 120, 206),
        _r("SC", 150, 180, 195, 206),
        _r("Date of Registration", 20, 215, 230, 241),
        _r("14/03/2019", 260, 215, 390, 241),
        _r("Address", 20, 250, 110, 276),
        _r("Ward 4, Near School", 150, 250, 390, 276),
        _r("Village", 20, 285, 100, 311),
        _r("Rampur", 150, 285, 260, 311),
        _r("Gram Panchayat", 20, 320, 180, 346),
        _r("Rampur", 210, 320, 320, 346),
        _r("Block", 20, 355, 85, 381),
        _r("Sanganer", 120, 355, 240, 381),
        _r("District", 300, 355, 380, 381),
        _r("Jaipur", 410, 355, 500, 381),
        _r("State", 540, 355, 600, 381),
        _r("Rajasthan", 630, 355, 760, 381),
        _r("Whether BPL", 20, 390, 145, 416),
        _r("Yes", 170, 390, 220, 416),
        _r("Family ID", 300, 390, 390, 416),
        _r("FAM-01452", 420, 390, 550, 416),
        _r("Details of applicants", 20, 435, 260, 461),
        _r("Sl. No.", 20, 480, 75, 506),
        _r("Name", 105, 480, 190, 506),
        _r("Father's/Husband's Name", 265, 480, 480, 506),
        _r("Male/Female", 525, 480, 620, 506),
        _r("Age", 680, 480, 730, 506),
        _r("1", 35, 525, 55, 551),
        _r("SITA DEVI", 105, 525, 220, 551),
        _r("RAM LAL", 300, 525, 415, 551),
        _r("Female", 535, 525, 605, 551),
        _r("39", 690, 525, 720, 551),
        _r("2", 35, 565, 55, 591),
        _r("MOHAN LAL", 105, 565, 230, 591),
        _r("RAM LAL", 300, 565, 415, 591),
        _r("Male", 535, 565, 595, 591),
        _r("42", 690, 565, 720, 591),


        _r("Aadhaar No.", 20, 630, 150, 656),
        _r("1234 5678 9012", 180, 630, 360, 656),
    ]


class TestNregaExtractor:
    def test_annexure_five_household_and_multiple_members(self):
        fields = extract_nrega(_english_job_card())

        assert fields.job_card_number == "RJ-27-001-002-0008147/00"
        assert fields.head_of_household == "SITA DEVI"
        assert fields.category == "SC"
        assert fields.registration_date == "14/03/2019"
        assert fields.validity_from == "01/04/2019"
        assert fields.validity_to == "31/03/2024"
        assert fields.address == "Ward 4, Near School"
        assert fields.village == "Rampur"
        assert fields.gram_panchayat == "Rampur"
        assert fields.block == "Sanganer"
        assert fields.district == "Jaipur"
        assert fields.state == "Rajasthan"
        assert fields.bpl_status is True
        assert fields.family_id == "FAM-01452"
        assert fields.members == [
            NregaMember(
                serial_number="1",
                name="SITA DEVI",
                father_or_husband_name="RAM LAL",
                gender="FEMALE",
                age=39,
            ),
            NregaMember(
                serial_number="2",
                name="MOHAN LAL",
                father_or_husband_name="RAM LAL",
                gender="MALE",
                age=42,
            ),
        ]

    def test_hindi_labels_and_member_table(self):
        regions = [
            _r("जॉब कार्ड संख्या: UP-65-001-003-00876700/342", 20, 30, 550, 60),
            _r("परिवार के मुखिया का नाम", 20, 80, 270, 108),
            _r("कमला देवी", 300, 80, 450, 108),
            _r("ग्राम पंचायत: देवपुर", 20, 125, 270, 153),
            _r("विकास खंड: फूलपुर", 20, 165, 270, 193),
            _r("जिला: प्रयागराज", 20, 205, 270, 233),
            _r("पंजीकरण दिनांक: 02-07-2018", 20, 245, 360, 273),
            _r("क्रम संख्या", 20, 315, 90, 343),
            _r("सदस्य का नाम", 120, 315, 250, 343),
            _r("पिता पति का नाम", 300, 315, 450, 343),
            _r("लिंग", 500, 315, 550, 343),
            _r("आयु", 610, 315, 655, 343),
            _r("1", 40, 360, 55, 388),
            _r("कमला देवी", 125, 360, 235, 388),
            _r("राम प्रसाद", 310, 360, 425, 388),
            _r("महिला", 500, 360, 565, 388),
            _r("36", 615, 360, 645, 388),
            _r("2", 40, 400, 55, 428),
            _r("सुनील कुमार", 125, 400, 245, 428),
            _r("राम प्रसाद", 310, 400, 425, 428),
            _r("पुरुष", 500, 400, 555, 428),
            _r("22", 615, 400, 645, 428),
        ]

        fields = extract_nrega(regions)

        assert fields.job_card_number == "UP-65-001-003-00876700/342"
        assert fields.head_of_household == "कमला देवी"
        assert fields.gram_panchayat == "देवपुर"
        assert fields.block == "फूलपुर"
        assert fields.district == "प्रयागराज"
        assert fields.registration_date == "02-07-2018"
        assert [member.name for member in fields.members] == ["कमला देवी", "सुनील कुमार"]
        assert [member.gender for member in fields.members] == ["FEMALE", "MALE"]
        assert [member.age for member in fields.members] == [36, 22]

    def test_bengali_and_telugu_location_labels(self):
        bengali = [
            _r("জব কার্ড নং: WB-12-004-009-000125/01", 20, 30, 500, 60),
            _r("পরিবারের প্রধানের নাম: মীনা দাস", 20, 80, 420, 110),
            _r("গ্রাম পঞ্চায়েত: হরিপুর", 20, 125, 350, 155),
            _r("ব্লক: গঙ্গারামপুর", 20, 165, 320, 195),
            _r("জেলা: দক্ষিণ দিনাজপুর", 20, 205, 360, 235),
        ]
        telugu = [
            _r("జాబ్ కార్డ్ నంబర్: AP-03-012-041-000778/00", 20, 30, 530, 60),
            _r("కుటుంబ యజమాని పేరు: లక్ష్మి", 20, 80, 380, 110),
            _r("గ్రామ పంచాయతీ: కొత్తపల్లి", 20, 125, 380, 155),
            _r("మండలం: నంద్యాల", 20, 165, 320, 195),
            _r("జిల్లా: కర్నూలు", 20, 205, 300, 235),
        ]

        wb = extract_nrega(bengali)
        ap = extract_nrega(telugu)

        assert wb.job_card_number == "WB-12-004-009-000125/01"
        assert wb.head_of_household == "মীনা দাস"
        assert wb.gram_panchayat == "হরিপুর"
        assert wb.block == "গঙ্গারামপুর"
        assert wb.district == "দক্ষিণ দিনাজপুর"
        assert ap.job_card_number == "AP-03-012-041-000778/00"
        assert ap.head_of_household == "లక్ష్మి"
        assert ap.gram_panchayat == "కొత్తపల్లి"
        assert ap.block == "నంద్యాల"
        assert ap.district == "కర్నూలు"

    def test_noisy_english_labels_and_numeric_ocr_confusions(self):
        regions = [
            _r("J0B CARD N0.", 20, 30, 170, 58, conf=0.61),
            _r("RJ-27-OO1-OO2-OOO8147/OO", 190, 30, 520, 58),
            _r("Grarn Panchayat", 20, 80, 190, 108, conf=0.65),
            _r("Rampur", 220, 80, 320, 108),
        ]

        fields = extract_nrega(regions)

        assert fields.job_card_number == "RJ-27-001-002-0008147/00"
        assert fields.gram_panchayat == "Rampur"

    def test_job_card_number_can_be_split_between_regions(self):
        regions = [
            _r("Job Card Number", 20, 30, 180, 58),
            _r("KA-25-006-", 210, 30, 340, 58),
            _r("014-00037800/136", 345, 30, 560, 58),
        ]

        fields = extract_nrega(regions)

        assert fields.job_card_number == "KA-25-006-014-00037800/136"

    def test_compact_pipe_separated_member_rows(self):
        regions = [
            _r("Details of applicants", 20, 100, 250, 128),
            _r("Sl No | Name | Father's/Husband's Name | Sex | Age", 20, 145, 700, 175),
            _r("1 | SITA DEVI | RAM LAL | Female | 39", 20, 190, 620, 220),
            _r("2 | MOHAN LAL | RAM LAL | M | 42", 20, 230, 600, 260),
        ]

        fields = extract_nrega(regions)

        assert fields.members == [
            NregaMember("1", "SITA DEVI", "RAM LAL", "FEMALE", 39),
            NregaMember("2", "MOHAN LAL", "RAM LAL", "MALE", 42),
        ]

    def test_bpl_no_and_non_bpl_text_is_not_guessed(self):
        no_card = [
            _r("Whether BPL", 20, 30, 150, 58),
            _r("No", 180, 30, 220, 58),
        ]
        unknown_card = [
            _r("Whether BPL: Pending verification", 20, 30, 390, 58),
        ]

        assert extract_nrega(no_card).bpl_status is False
        assert extract_nrega(unknown_card).bpl_status is None

    def test_validity_with_separate_from_and_to_labels(self):
        regions = [
            _r("Valid From", 20, 30, 130, 58),
            _r("01 Apr 2018", 160, 30, 290, 58),
            _r("Valid To", 330, 30, 420, 58),
            _r("31 Mar 2023", 450, 30, 590, 58),
        ]

        fields = extract_nrega(regions)

        assert fields.validity_from == "01 Apr 2018"
        assert fields.validity_to == "31 Mar 2023"

    def test_identifier_shape_rejects_pan_aadhaar_phone_and_dl(self):
        regions = [
            _r("ABCDE1234F", 20, 30, 170, 58),
            _r("1234 5678 9012", 20, 70, 200, 98),
            _r("+91 98765 43210", 20, 110, 200, 138),
            _r("DL-0420110149646", 20, 150, 220, 178),
        ]

        assert extract_nrega(regions).job_card_number is None

    def test_member_age_must_be_plausible_for_registered_adult(self):
        regions = [
            _r("Sl. No.", 20, 100, 75, 126),
            _r("Name", 105, 100, 190, 126),
            _r("Gender", 300, 100, 380, 126),
            _r("Age", 470, 100, 520, 126),
            _r("1", 35, 145, 55, 171),
            _r("MINOR NUMBER NOISE", 105, 145, 260, 171),
            _r("Female", 305, 145, 375, 171),
            _r("7", 480, 145, 495, 171),
            _r("2", 35, 185, 55, 211),
            _r("VALID ADULT", 105, 185, 235, 211),
            _r("Male", 305, 185, 365, 211),
            _r("101", 480, 185, 515, 211),
        ]

        fields = extract_nrega(regions)



        assert [member.age for member in fields.members] == [None, None]

    def test_partial_card_does_not_fabricate_missing_fields(self):
        fields = extract_nrega(
            [
                _r("MGNREGA", 20, 20, 140, 48),
                _r("District: Gaya", 20, 70, 220, 98),
            ]
        )

        assert fields.district == "Gaya"
        assert fields.job_card_number is None
        assert fields.head_of_household is None
        assert fields.members == []

    def test_empty_regions_return_default_contract(self):
        assert extract_nrega([]) == NregaFields()

    def test_contract_excludes_high_risk_secondary_identifiers(self):
        fields = extract_nrega(_english_job_card())

        for forbidden in (
            "aadhaar_number",
            "bank_account_number",
            "insurance_policy_number",
            "epic_number",
        ):
            assert not hasattr(fields, forbidden)

    def test_contract_field_names(self):
        fields = extract_nrega([])

        for name in (
            "job_card_number",
            "head_of_household",
            "category",
            "registration_date",
            "validity_from",
            "validity_to",
            "address",
            "village",
            "gram_panchayat",
            "block",
            "district",
            "state",
            "bpl_status",
            "family_id",
            "members",
        ):
            assert hasattr(fields, name)
