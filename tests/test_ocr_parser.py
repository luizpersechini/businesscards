"""
Tests for the OCR-text → ContactInfo regex parser used by GLM-OCR
(`OllamaVisionProvider._parse_ocr_to_contact`).

These tests guard against regressions documented in recent commits:
  - "Improve OCR parser: fix ZIP false-positives, name/company swap, all-caps"
"""

import unittest

from utils.providers.ollama_provider import OllamaVisionProvider


parse = OllamaVisionProvider._parse_ocr_to_contact


class TestEmailExtraction(unittest.TestCase):
    def test_extracts_simple_email(self):
        c = parse("Joel Schimchak\njoel@acme.com")
        self.assertEqual(c["email"], "joel@acme.com")

    def test_lowercases_email(self):
        c = parse("Contact: JOEL@ACME.COM")
        self.assertEqual(c["email"], "joel@acme.com")

    def test_handles_plus_addressing(self):
        c = parse("foo+bar@example.co.uk")
        self.assertEqual(c["email"], "foo+bar@example.co.uk")


class TestPhoneVsZIP(unittest.TestCase):
    """CEP (Brazilian ZIP) NNNNN-NNN must NOT be treated as a phone."""

    def test_brazilian_cep_is_not_phone(self):
        c = parse("Rua Augusta 100\n01304-001\nSão Paulo")
        self.assertIsNone(c["phone"])
        self.assertEqual(c["zip"], "01304-001")

    def test_cep_inline_with_prefix_not_treated_as_phone(self):
        # Bare "CEP 01304-001" doesn't match the CEP-only line pattern, so it
        # won't be set as zip — but it must NOT be misclassified as a phone.
        c = parse("CEP 01304-001")
        self.assertIsNone(c["phone"])

    def test_real_phone_with_country_code_extracted(self):
        c = parse("+55 11 99999-9999")
        self.assertIsNotNone(c["phone"])
        self.assertIn("9999", c["phone"])

    def test_us_phone_extracted(self):
        c = parse("(555) 234-5678")
        self.assertIsNotNone(c["phone"])

    def test_two_phones_split_into_phone_and_mobile(self):
        c = parse("+55 11 3000-1000\n+55 11 99999-9999")
        self.assertIsNotNone(c["phone"])
        self.assertIsNotNone(c["mobile"])


class TestNameVsCompany(unittest.TestCase):
    def test_person_name_assigned_to_first_last(self):
        c = parse("Joel Schimchak\nSales Manager\nAcme Corp\njoel@acme.com")
        self.assertEqual(c["firstName"], "Joel")
        self.assertEqual(c["lastName"], "Schimchak")

    def test_company_with_corp_keyword_not_taken_as_name(self):
        # Without this guard, "Acme Corp" used to get parsed as a name first.
        c = parse("Acme Corp\nJoel Schimchak\njoel@acme.com")
        self.assertEqual(c["firstName"], "Joel")
        self.assertEqual(c["lastName"], "Schimchak")
        self.assertEqual(c["company"], "Acme Corp")

    def test_title_keyword_line_not_taken_as_name(self):
        c = parse("Sales Manager\nJoel Schimchak\njoel@acme.com")
        self.assertEqual(c["firstName"], "Joel")
        self.assertEqual(c["title"], "Sales Manager")


class TestAllCapsHandling(unittest.TestCase):
    """All-caps lines are usually logos / department headers, not names."""

    def test_all_caps_logo_skipped_for_name(self):
        c = parse("ACME GLOBAL\nJoel Schimchak\nDirector\njoel@acme.com")
        self.assertEqual(c["firstName"], "Joel")

    def test_all_caps_not_picked_as_company_when_better_candidate_exists(self):
        # All-caps logo at top should not block a real corp-keyword line below.
        c = parse("ACME\nJoel Silva\nGerente\nAcme Tecnologia Ltda")
        self.assertEqual(c["company"], "Acme Tecnologia Ltda")


class TestWebsiteAndLinkedIn(unittest.TestCase):
    def test_extracts_website_with_protocol(self):
        c = parse("https://www.acme.com")
        self.assertIn("acme.com", c["website"])

    def test_extracts_bare_domain(self):
        c = parse("www.acme.com.br")
        self.assertIn("acme.com.br", c["website"])

    def test_linkedin_separate_from_website(self):
        c = parse("linkedin.com/in/joel\nwww.acme.com")
        self.assertIn("linkedin.com", c["linkedin"])
        self.assertIn("acme.com", c["website"])
        self.assertNotIn("linkedin", c["website"])

    def test_email_line_not_mistaken_for_website(self):
        c = parse("joel@acme.com")
        self.assertEqual(c["email"], "joel@acme.com")
        self.assertIsNone(c["website"])


class TestEmptyAndMalformed(unittest.TestCase):
    def test_empty_input_returns_all_none(self):
        c = parse("")
        for v in c.values():
            self.assertIsNone(v)

    def test_returns_dict_even_on_garbage_input(self):
        c = parse("###---***")
        self.assertIsInstance(c, dict)
        # Should contain the documented keys
        self.assertIn("email", c)
        self.assertIn("firstName", c)


if __name__ == "__main__":
    unittest.main()
