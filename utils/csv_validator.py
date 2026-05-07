"""
CSV Validator Module
Validates CSV format for Outlook compatibility and detects potential issues.
"""

import csv
from io import StringIO
from typing import Dict, List, Tuple


class CSVValidator:
    """Validates CSV format for Outlook compatibility."""
    
    # Expected Outlook field names (multiple variations)
    OUTLOOK_FIELD_VARIANTS = {
        'email': ['E-mail Address', 'Email Address', 'Email', 'E-mail', 'Primary Email'],
        'phone': ['Business Phone', 'Phone', 'Work Phone', 'Primary Phone', 'Telephone'],
        'mobile': ['Mobile Phone', 'Cell Phone', 'Mobile', 'Cellular Phone'],
        'first_name': ['First Name', 'FirstName', 'First', 'Given Name'],
        'last_name': ['Last Name', 'LastName', 'Last', 'Surname', 'Family Name'],
        'company': ['Company', 'Organization', 'Org', 'Business Name'],
        'job_title': ['Job Title', 'Title', 'Position', 'Job'],
    }
    
    def __init__(self):
        """Initialize the CSV validator."""
        pass
    
    def validate_csv(self, csv_data: bytes) -> Dict:
        """
        Validate CSV data for Outlook compatibility.
        
        Args:
            csv_data: CSV file content as bytes
            
        Returns:
            Dictionary with validation results:
                - valid: bool - Whether CSV is valid
                - encoding: str - Detected encoding
                - has_bom: bool - Whether BOM is present
                - line_ending: str - Detected line ending type
                - field_names: List[str] - Detected field names
                - issues: List[str] - List of issues found
                - recommendations: List[str] - Recommended fixes
        """
        issues = []
        recommendations = []
        
        # Check encoding
        encoding, has_bom = self._detect_encoding(csv_data)
        if encoding != 'utf-8-sig':
            issues.append(f"Encoding should be UTF-8 with BOM (utf-8-sig), detected: {encoding}")
            recommendations.append("Save CSV with UTF-8-sig encoding")
        
        # Decode CSV
        try:
            if encoding == 'utf-8-sig' or has_bom:
                text = csv_data.decode('utf-8-sig')
            else:
                text = csv_data.decode(encoding)
        except UnicodeDecodeError as e:
            return {
                'valid': False,
                'encoding': encoding,
                'has_bom': has_bom,
                'line_ending': 'unknown',
                'field_names': [],
                'issues': [f"Encoding error: {str(e)}"],
                'recommendations': ["Fix file encoding to UTF-8-sig"]
            }
        
        # Check line endings
        line_ending = self._detect_line_endings(text)
        if line_ending != '\r\n':
            issues.append(f"Line endings should be CRLF (\\r\\n), detected: {repr(line_ending)}")
            recommendations.append("Use Windows-style line endings (CRLF)")
        
        # Parse CSV
        try:
            lines = text.splitlines()
            if not lines:
                return {
                    'valid': False,
                    'encoding': encoding,
                    'has_bom': has_bom,
                    'line_ending': line_ending,
                    'field_names': [],
                    'issues': ['CSV file is empty'],
                    'recommendations': []
                }
            
            # Get field names from header
            reader = csv.reader(StringIO(text))
            field_names = next(reader)
            
            # Check for required fields
            required_fields = self._check_required_fields(field_names)
            if not required_fields['has_email']:
                issues.append("No email field detected in headers")
                recommendations.append("Include 'E-mail Address' or 'Email Address' field")
            
            if not required_fields['has_phone']:
                issues.append("No phone field detected in headers")
                recommendations.append("Include 'Business Phone' or 'Phone' field")
            
            # Check for problematic characters
            data_issues = self._check_data_issues(text, field_names)
            issues.extend(data_issues)
            
            # Check field order
            order_issues = self._check_field_order(field_names)
            if order_issues:
                issues.extend(order_issues)
                recommendations.append("Reorder fields: Name fields first, then Company, Email, Phone")
            
        except Exception as e:
            issues.append(f"CSV parsing error: {str(e)}")
            recommendations.append("Check CSV format and ensure proper quoting")
        
        return {
            'valid': len(issues) == 0,
            'encoding': encoding,
            'has_bom': has_bom,
            'line_ending': line_ending,
            'field_names': field_names if 'field_names' in locals() else [],
            'issues': issues,
            'recommendations': recommendations,
            'required_fields': required_fields if 'required_fields' in locals() else {}
        }
    
    def _detect_encoding(self, data: bytes) -> Tuple[str, bool]:
        """Detect encoding and BOM presence."""
        # Check for BOM
        if data.startswith(b'\xef\xbb\xbf'):
            return 'utf-8-sig', True
        elif data.startswith(b'\xff\xfe'):
            return 'utf-16-le', True
        elif data.startswith(b'\xfe\xff'):
            return 'utf-16-be', True
        
        # Try to decode as UTF-8
        try:
            data.decode('utf-8')
            return 'utf-8', False
        except UnicodeDecodeError:
            pass
        
        # Default assumption
        return 'utf-8', False
    
    def _detect_line_endings(self, text: str) -> str:
        """Detect line ending type."""
        if '\r\n' in text:
            return '\r\n'
        elif '\r' in text:
            return '\r'
        elif '\n' in text:
            return '\n'
        return 'unknown'
    
    def _check_required_fields(self, field_names: List[str]) -> Dict:
        """Check if required Outlook fields are present."""
        result = {
            'has_email': False,
            'has_phone': False,
            'has_first_name': False,
            'has_last_name': False,
            'has_company': False,
            'email_field': None,
            'phone_field': None,
        }
        
        field_names_lower = [f.lower() for f in field_names]
        
        # Check for email
        for variant in self.OUTLOOK_FIELD_VARIANTS['email']:
            if variant.lower() in field_names_lower:
                idx = field_names_lower.index(variant.lower())
                result['has_email'] = True
                result['email_field'] = field_names[idx]
                break
        
        # Check for phone
        for variant in self.OUTLOOK_FIELD_VARIANTS['phone']:
            if variant.lower() in field_names_lower:
                idx = field_names_lower.index(variant.lower())
                result['has_phone'] = True
                result['phone_field'] = field_names[idx]
                break
        
        # Check for name fields
        for variant in self.OUTLOOK_FIELD_VARIANTS['first_name']:
            if variant.lower() in field_names_lower:
                result['has_first_name'] = True
                break
        
        for variant in self.OUTLOOK_FIELD_VARIANTS['last_name']:
            if variant.lower() in field_names_lower:
                result['has_last_name'] = True
                break
        
        # Check for company
        for variant in self.OUTLOOK_FIELD_VARIANTS['company']:
            if variant.lower() in field_names_lower:
                result['has_company'] = True
                break
        
        return result
    
    def _check_data_issues(self, text: str, field_names: List[str]) -> List[str]:
        """Check for problematic data (commas in emails, quotes, etc.)."""
        issues = []
        
        try:
            reader = csv.DictReader(StringIO(text))
            for i, row in enumerate(reader):
                # Check email fields
                for field in field_names:
                    if 'email' in field.lower() or 'e-mail' in field.lower():
                        value = row.get(field, '').strip()
                        if value:
                            # Check for commas in email
                            if ',' in value:
                                issues.append(f"Row {i+2}: Email contains comma: {value[:50]}")
                            # Check for invalid email format
                            if '@' not in value:
                                issues.append(f"Row {i+2}: Invalid email format (no @): {value[:50]}")
                    
                    # Check for unclosed quotes
                    if '"' in str(row.get(field, '')):
                        # Count quotes - should be even
                        quote_count = str(row.get(field, '')).count('"')
                        if quote_count % 2 != 0:
                            issues.append(f"Row {i+2}, Field '{field}': Unclosed quote detected")
                
                # Limit checks to first 100 rows
                if i >= 99:
                    break
        except Exception as e:
            issues.append(f"Error checking data: {str(e)}")
        
        return issues
    
    def _check_field_order(self, field_names: List[str]) -> List[str]:
        """Check if field order follows Outlook best practices."""
        issues = []
        
        # Find positions of key fields
        email_pos = None
        phone_pos = None
        first_name_pos = None
        company_pos = None
        
        for i, field in enumerate(field_names):
            field_lower = field.lower()
            if 'email' in field_lower or 'e-mail' in field_lower:
                email_pos = i
            if 'phone' in field_lower and 'mobile' not in field_lower:
                phone_pos = i
            if 'first name' in field_lower or field_lower == 'firstname':
                first_name_pos = i
            if 'company' in field_lower:
                company_pos = i
        
        # Email should be within first 10 fields
        if email_pos is not None and email_pos > 10:
            issues.append(f"Email field at position {email_pos+1} - should be in first 10 fields for better mapping")
        
        # Phone should be within first 15 fields
        if phone_pos is not None and phone_pos > 15:
            issues.append(f"Phone field at position {phone_pos+1} - should be in first 15 fields for better mapping")
        
        return issues
    
    def compare_with_outlook_format(self, csv_data: bytes) -> Dict:
        """
        Compare CSV format with Outlook's expected format.
        
        Args:
            csv_data: CSV file content as bytes
            
        Returns:
            Dictionary with comparison results
        """
        validation = self.validate_csv(csv_data)
        
        # Ideal Outlook CSV format characteristics
        ideal_format = {
            'encoding': 'utf-8-sig',
            'line_ending': '\r\n',
            'field_order': ['First Name', 'Last Name', 'Company', 'E-mail Address', 'Business Phone'],
            'quoting': 'all fields quoted',
        }
        
        comparison = {
            'encoding_match': validation['encoding'] == ideal_format['encoding'],
            'line_ending_match': validation['line_ending'] == ideal_format['line_ending'],
            'field_names_match': validation['required_fields'].get('has_email', False) and \
                                validation['required_fields'].get('has_phone', False),
            'issues': validation['issues'],
            'recommendations': validation['recommendations'],
        }
        
        return comparison
    
    def generate_diagnostic_report(self, csv_data: bytes) -> str:
        """
        Generate a detailed diagnostic report for CSV file.
        
        Args:
            csv_data: CSV file content as bytes
            
        Returns:
            Formatted diagnostic report as string
        """
        validation = self.validate_csv(csv_data)
        
        report = []
        report.append("=" * 60)
        report.append("CSV OUTLOOK COMPATIBILITY DIAGNOSTIC REPORT")
        report.append("=" * 60)
        report.append("")
        
        # Summary
        status = "VALID" if validation['valid'] else "ISSUES DETECTED"
        report.append(f"Status: {status}")
        report.append(f"Encoding: {validation['encoding']} (BOM: {validation['has_bom']})")
        report.append(f"Line Endings: {repr(validation['line_ending'])}")
        report.append("")
        
        # Field names
        report.append("Field Names:")
        for i, field in enumerate(validation['field_names'], 1):
            marker = ""
            if 'email' in field.lower():
                marker = " <-- Email field"
            elif 'phone' in field.lower():
                marker = " <-- Phone field"
            report.append(f"  {i}. {field}{marker}")
        report.append("")
        
        # Required fields
        req = validation.get('required_fields', {})
        report.append("Required Fields Check:")
        report.append(f"  First Name: {'✓' if req.get('has_first_name') else '✗'}")
        report.append(f"  Last Name: {'✓' if req.get('has_last_name') else '✗'}")
        report.append(f"  Company: {'✓' if req.get('has_company') else '✗'}")
        report.append(f"  Email: {'✓' if req.get('has_email') else '✗'} ({req.get('email_field', 'Not found')})")
        report.append(f"  Phone: {'✓' if req.get('has_phone') else '✗'} ({req.get('phone_field', 'Not found')})")
        report.append("")
        
        # Issues
        if validation['issues']:
            report.append("Issues Detected:")
            for issue in validation['issues']:
                report.append(f"  ✗ {issue}")
            report.append("")
        
        # Recommendations
        if validation['recommendations']:
            report.append("Recommendations:")
            for rec in validation['recommendations']:
                report.append(f"  → {rec}")
            report.append("")
        
        report.append("=" * 60)
        
        return "\n".join(report)

