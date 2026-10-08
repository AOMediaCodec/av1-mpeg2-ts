"""Abstract Test Suite (ATS) XML export for OGC/ISO conformance specifications."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING
from xml.etree.ElementTree import Element, SubElement, indent, tostring

if TYPE_CHECKING:
    from bs4 import BeautifulSoup


@dataclass
class AtsTestCase:
    test_id: str  # e.g. "req-7-001"
    title: str
    requirement: str  # Requirement text
    test_purpose: str  # What the test verifies
    test_method: str  # "Visual inspection" / "Software test" / "Conformance test"
    test_type: str  # "Capabilities" / "Performance"
    section_ref: str  # e.g. "7.3.2"


@dataclass
class AtsConformanceClass:
    class_id: str
    title: str
    target: str  # URI or descriptive string
    test_cases: list[AtsTestCase] = field(default_factory=list)


def extract_test_cases_from_soup(soup: BeautifulSoup) -> list[AtsTestCase]:
    """Find all requirement elements with data-req-id attributes."""
    test_cases: list[AtsTestCase] = []

    for element in soup.find_all(attrs={"data-req-id": True}):
        test_id = element["data-req-id"]

        # Title: first <strong> or <b> child text, fallback to "Requirement {test_id}"
        strong = element.find("strong") or element.find("b")
        title = strong.get_text(strip=True) if strong else f"Requirement {test_id}"

        # Full text content as requirement
        requirement = element.get_text(separator=" ", strip=True)

        # Test purpose
        test_purpose = f"Verify compliance with {test_id}"

        # Test method: "Software test" if any <code> child, else "Visual inspection"
        test_method = "Software test" if element.find("code") else "Visual inspection"

        # Test type
        test_type = "Capabilities"

        # Section ref: nearest ancestor <section> id
        section_ref = ""
        for parent in element.parents:
            if hasattr(parent, "name") and parent.name == "section":
                section_ref = parent.get("id", "")
                break

        test_cases.append(
            AtsTestCase(
                test_id=test_id,
                title=title,
                requirement=requirement,
                test_purpose=test_purpose,
                test_method=test_method,
                test_type=test_type,
                section_ref=section_ref,
            )
        )

    return test_cases


def group_into_conformance_classes(
    test_cases: list[AtsTestCase],
    soup: BeautifulSoup,
) -> list[AtsConformanceClass]:
    """Group test cases by their parent section heading."""
    if not test_cases:
        return []

    # Group by first 3 characters of test_id (e.g. "REQ", "PER", "REC")
    groups: dict[str, list[AtsTestCase]] = {}
    for tc in test_cases:
        group_key = tc.section_ref or (tc.test_id[:3] if len(tc.test_id) >= 3 else tc.test_id)
        groups.setdefault(group_key, []).append(tc)

    # If only one unique key and it equals a meaningless fragment, put all in one class
    if len(groups) == 1:
        # Try to derive title from section heading using section_ref of first case
        section_ref = test_cases[0].section_ref
        cc_title = "General Requirements"
        if section_ref:
            section_el = soup.find(id=section_ref)
            if section_el:
                heading = section_el.find(["h1", "h2", "h3", "h4", "h5", "h6"])
                if heading:
                    cc_title = heading.get_text(strip=True)
        return [
            AtsConformanceClass(
                class_id="cc-1",
                title=cc_title,
                target=section_ref or "general",
                test_cases=list(test_cases),
            )
        ]

    conformance_classes: list[AtsConformanceClass] = []
    for idx, (group_key, cases) in enumerate(groups.items(), start=1):
        # Derive title from the first case's section ref
        section_ref = cases[0].section_ref
        cc_title = f"{group_key} Requirements"
        if section_ref:
            section_el = soup.find(id=section_ref)
            if section_el:
                heading = section_el.find(["h1", "h2", "h3", "h4", "h5", "h6"])
                if heading:
                    cc_title = heading.get_text(strip=True)

        conformance_classes.append(
            AtsConformanceClass(
                class_id=f"cc-{idx}",
                title=cc_title,
                target=section_ref or group_key.lower(),
                test_cases=cases,
            )
        )

    return conformance_classes


def build_ats_xml(classes: list[AtsConformanceClass], title: str) -> str:
    """Build ISO-style ATS XML string."""
    root = Element("ats:AbstractTestSuite")
    root.set("xmlns:ats", "http://www.opengis.net/ats/1.0")
    root.set("xmlns:ctl", "http://www.occamlab.com/ctl")
    root.set("title", title)

    for cc in classes:
        cc_elem = SubElement(root, "ats:conformanceClass")
        cc_elem.set("id", cc.class_id)
        cc_elem.set("title", cc.title)
        if cc.target:
            cc_elem.set("target", cc.target)

        for tc in cc.test_cases:
            tc_elem = SubElement(cc_elem, "ats:testCase")
            tc_elem.set("id", tc.test_id)
            tc_elem.set("title", tc.title)

            req_elem = SubElement(tc_elem, "ats:requirement")
            req_elem.text = tc.requirement

            purpose_elem = SubElement(tc_elem, "ats:testPurpose")
            purpose_elem.text = tc.test_purpose

            method_elem = SubElement(tc_elem, "ats:testMethod")
            method_elem.text = tc.test_method

            type_elem = SubElement(tc_elem, "ats:testType")
            type_elem.text = tc.test_type

    indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(root, encoding="unicode")


def export_ats(
    soup: BeautifulSoup,
    output_path: Path,
    title: str = "Abstract Test Suite",
) -> Path | None:
    """Extract requirements from soup and write ATS XML to output_path."""
    test_cases = extract_test_cases_from_soup(soup)
    if not test_cases:
        return None

    classes = group_into_conformance_classes(test_cases, soup)
    xml_str = build_ats_xml(classes, title)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(xml_str, encoding="utf-8")
    return output_path
