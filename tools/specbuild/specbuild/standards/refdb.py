"""Curated reference database of well-known standards.

Provides a local knowledge base of commonly cited standards in video
coding and related domains.  Used by :mod:`specbuild.checks.refvalidate`
to validate bibliography entries without depending on external APIs at
build time.

The database covers ISO/IEC MPEG family standards (14496, 23008, 23090,
23094), ITU-T H.26x recommendations, IETF RFCs, IEEE standards, and
foundational ISO standards.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class StandardRef:
    """Metadata for a known standard or recommendation.

    Attributes:
        body: Standards body abbreviation (``"ISO"``, ``"IEC"``,
            ``"ITU-T"``, ``"IETF"``, ``"IEEE"``).
        docnumber: Canonical document identifier (e.g. ``"14496-10"``,
            ``"H.265"``, ``"RFC 6386"``).
        title: Short descriptive title.
        current_year: Year of the latest known edition (empty string if
            not tracked).
        status: One of ``"active"``, ``"withdrawn"``, ``"superseded"``.
        successor: Document number of the successor, if superseded.
        parts: Known part numbers, when the standard is a multi-part
            family.
    """

    body: str
    docnumber: str
    title: str
    current_year: str = ""
    status: str = "active"
    successor: str = ""
    parts: tuple[str, ...] = field(default_factory=tuple)


# ═══════════════════════════════════════════════════════════════════════════
# Curated database
# ═══════════════════════════════════════════════════════════════════════════

KNOWN_STANDARDS: dict[str, StandardRef] = {}


def _add(ref: StandardRef, *aliases: str) -> None:
    """Register a :class:`StandardRef` under its canonical key and aliases."""
    key = f"{ref.body} {ref.docnumber}".upper()
    KNOWN_STANDARDS[key] = ref
    for alias in aliases:
        KNOWN_STANDARDS[alias.upper()] = ref


# ---------------------------------------------------------------------------
# ISO/IEC 14496 — MPEG-4
# ---------------------------------------------------------------------------

_add(StandardRef("ISO/IEC", "14496-1", "MPEG-4 Systems", "2010"))
_add(StandardRef("ISO/IEC", "14496-2", "MPEG-4 Visual", "2004"))
_add(StandardRef("ISO/IEC", "14496-3", "MPEG-4 Audio (AAC)", "2019"))
_add(StandardRef("ISO/IEC", "14496-4", "MPEG-4 Conformance testing", "2004"))
_add(StandardRef("ISO/IEC", "14496-5", "MPEG-4 Reference software", "2017"))
_add(StandardRef("ISO/IEC", "14496-10", "MPEG-4 AVC (H.264)", "2022"), "ISO/IEC 14496-10", "AVC")
_add(StandardRef("ISO/IEC", "14496-12", "ISO base media file format (ISOBMFF)", "2022"))
_add(StandardRef("ISO/IEC", "14496-14", "MP4 file format", "2020"))
_add(StandardRef("ISO/IEC", "14496-15", "Carriage of NAL unit structured video in ISOBMFF", "2022"))
_add(StandardRef("ISO/IEC", "14496-16", "Animation Framework eXtension (AFX)", "2011"))
_add(StandardRef("ISO/IEC", "14496-17", "Streaming text format", "2006"))
_add(
    StandardRef(
        "ISO/IEC", "14496-20", "Lightweight Application Scene Representation (LASeR)", "2008"
    )
)
_add(StandardRef("ISO/IEC", "14496-22", "Open Font Format", "2019"))
_add(StandardRef("ISO/IEC", "14496-26", "MPEG-4 Audio conformance", "2010"))
_add(StandardRef("ISO/IEC", "14496-27", "3D Graphics conformance", "2009"))
_add(StandardRef("ISO/IEC", "14496-30", "Timed text and other visual overlays in ISOBMFF", "2018"))
_add(StandardRef("ISO/IEC", "14496-33", "Internet video coding", "2019"))

# ---------------------------------------------------------------------------
# ISO/IEC 23008 — MPEG-H
# ---------------------------------------------------------------------------

_add(StandardRef("ISO/IEC", "23008-1", "MPEG-H Transport", "2023"))
_add(StandardRef("ISO/IEC", "23008-2", "HEVC (H.265)", "2024"), "HEVC")
_add(StandardRef("ISO/IEC", "23008-3", "MPEG-H 3D Audio", "2022"))
_add(StandardRef("ISO/IEC", "23008-4", "HEVC verification conformance", "2020"))
_add(StandardRef("ISO/IEC", "23008-5", "HEVC reference software", "2017"))
_add(StandardRef("ISO/IEC", "23008-7", "MV-HEVC (Multiview HEVC)", "2015"))
_add(StandardRef("ISO/IEC", "23008-8", "3D-HEVC", "2017"))
_add(StandardRef("ISO/IEC", "23008-9", "HEVC 3D Audio conformance", "2019"))
_add(StandardRef("ISO/IEC", "23008-10", "HEVC Screen Content Coding", "2016"))
_add(StandardRef("ISO/IEC", "23008-11", "MPEG-H Scene Description", "2020"))
_add(StandardRef("ISO/IEC", "23008-12", "HEIF (High Efficiency Image File Format)", "2022"), "HEIF")

# ---------------------------------------------------------------------------
# ISO/IEC 23090 — MPEG-I (Immersive)
# ---------------------------------------------------------------------------

_add(StandardRef("ISO/IEC", "23090-1", "MPEG Immersive Architectures", "2023"))
_add(StandardRef("ISO/IEC", "23090-2", "Omnidirectional Media Format (OMAF)", "2023"))
_add(StandardRef("ISO/IEC", "23090-3", "VVC (H.266)", "2024"), "VVC")
_add(StandardRef("ISO/IEC", "23090-4", "VVC reference software (VTM)", "2022"))
_add(
    StandardRef("ISO/IEC", "23090-5", "Visual Volumetric Video-based Coding (V3C) / V-PCC", "2023")
)
_add(StandardRef("ISO/IEC", "23090-6", "VVC conformance", "2023"))
_add(StandardRef("ISO/IEC", "23090-7", "VVC common test conditions", "2022"))
_add(StandardRef("ISO/IEC", "23090-8", "Neural Network Coding (NNC)", "2023"))
_add(StandardRef("ISO/IEC", "23090-9", "Geometry-based Point Cloud Compression (G-PCC)", "2023"))
_add(StandardRef("ISO/IEC", "23090-10", "Carriage of VVC in ISOBMFF", "2023"))
_add(StandardRef("ISO/IEC", "23090-11", "Supplemental Enhancement Information for VVC/V3C", "2023"))
_add(StandardRef("ISO/IEC", "23090-12", "MPEG Immersive Video (MIV)", "2023"))
_add(StandardRef("ISO/IEC", "23090-14", "Scene Description for MPEG Media", "2023"))

# ---------------------------------------------------------------------------
# ISO/IEC 23094 — MPEG-5
# ---------------------------------------------------------------------------

_add(StandardRef("ISO/IEC", "23094-1", "Essential Video Coding (EVC)", "2022"), "EVC")
_add(StandardRef("ISO/IEC", "23094-2", "EVC conformance", "2022"))
_add(StandardRef("ISO/IEC", "23094-3", "EVC reference software", "2023"))
_add(
    StandardRef("ISO/IEC", "23094-4", "LCEVC (Low Complexity Enhancement Video Coding)", "2023"),
    "LCEVC",
)

# ---------------------------------------------------------------------------
# ISO/IEC 21122 — JPEG XS
# ---------------------------------------------------------------------------

_add(StandardRef("ISO/IEC", "21122-1", "JPEG XS Core coding system", "2022"))
_add(StandardRef("ISO/IEC", "21122-2", "JPEG XS Profiles and buffer model", "2022"))
_add(StandardRef("ISO/IEC", "21122-3", "JPEG XS Transport and container formats", "2022"))

# ---------------------------------------------------------------------------
# ISO/IEC 18181 — JPEG XL
# ---------------------------------------------------------------------------

_add(StandardRef("ISO/IEC", "18181-1", "JPEG XL Core coding system", "2022"))
_add(StandardRef("ISO/IEC", "18181-2", "JPEG XL File format", "2022"))

# ---------------------------------------------------------------------------
# ITU-T H.26x — Video coding
# ---------------------------------------------------------------------------

_add(
    StandardRef(
        "ITU-T",
        "H.261",
        "Video codec for audiovisual services at p x 64 kbit/s",
        "1993",
        "superseded",
        "H.262",
    ),
    "H.261",
)
_add(
    StandardRef("ITU-T", "H.262", "Generic coding of moving pictures (MPEG-2 Video)", "2012"),
    "H.262",
)
_add(StandardRef("ITU-T", "H.263", "Video coding for low bit rate communication", "2005"), "H.263")
_add(StandardRef("ITU-T", "H.264", "Advanced video coding (AVC)", "2022"), "H.264")
_add(StandardRef("ITU-T", "H.265", "High efficiency video coding (HEVC)", "2024"), "H.265")
_add(StandardRef("ITU-T", "H.266", "Versatile video coding (VVC)", "2024"), "H.266")
_add(
    StandardRef("ITU-T", "H.274", "Versatile supplemental enhancement information", "2022"), "H.274"
)
_add(StandardRef("ITU-T", "H.222.0", "MPEG-2 Systems", "2022"), "H.222.0")

# ---------------------------------------------------------------------------
# ITU-T T.800/T.832 — JPEG 2000
# ---------------------------------------------------------------------------

_add(StandardRef("ITU-T", "T.800", "JPEG 2000 Core coding system", "2019"), "T.800")
_add(StandardRef("ITU-T", "T.801", "JPEG 2000 Extensions", "2019"), "T.801")
_add(StandardRef("ITU-T", "T.802", "JPEG 2000 Motion JPEG 2000", "2019"), "T.802")
_add(StandardRef("ITU-T", "T.832", "JPEG XR", "2019"), "T.832")

# ---------------------------------------------------------------------------
# IETF RFCs
# ---------------------------------------------------------------------------

_add(
    StandardRef("IETF", "RFC 2119", "Key words for use in RFCs (BCP 14)", "1997"),
    "RFC 2119",
    "RFC2119",
)
_add(
    StandardRef("IETF", "RFC 8174", "Ambiguity of Uppercase vs Lowercase in RFC 2119", "2017"),
    "RFC 8174",
    "RFC8174",
)
_add(
    StandardRef("IETF", "RFC 6386", "VP8 Data Format and Decoding Guide", "2011"),
    "RFC 6386",
    "RFC6386",
)
_add(
    StandardRef("IETF", "RFC 6716", "Definition of the Opus Audio Codec", "2012"),
    "RFC 6716",
    "RFC6716",
)
_add(
    StandardRef("IETF", "RFC 3550", "RTP: A Transport Protocol for Real-Time Applications", "2003"),
    "RFC 3550",
    "RFC3550",
)
_add(
    StandardRef("IETF", "RFC 6184", "RTP Payload Format for H.264 Video", "2011"),
    "RFC 6184",
    "RFC6184",
)
_add(StandardRef("IETF", "RFC 7798", "RTP Payload Format for HEVC", "2016"), "RFC 7798", "RFC7798")
_add(StandardRef("IETF", "RFC 9328", "RTP Payload Format for VVC", "2022"), "RFC 9328", "RFC9328")
_add(
    StandardRef("IETF", "RFC 2733", "An RTP Payload Format for Generic FEC", "1999"),
    "RFC 2733",
    "RFC2733",
)
_add(StandardRef("IETF", "RFC 6190", "RTP Payload Format for SVC", "2011"), "RFC 6190", "RFC6190")
_add(StandardRef("IETF", "RFC 7741", "RTP Payload Format for VP8", "2016"), "RFC 7741", "RFC7741")
_add(StandardRef("IETF", "RFC 7587", "RTP Payload Format for Opus", "2015"), "RFC 7587", "RFC7587")
_add(
    StandardRef("IETF", "RFC 2045", "MIME Part One: Format of Internet Message Bodies", "1996"),
    "RFC 2045",
    "RFC2045",
)
_add(StandardRef("IETF", "RFC 2046", "MIME Part Two: Media Types", "1996"), "RFC 2046", "RFC2046")
_add(
    StandardRef("IETF", "RFC 3986", "Uniform Resource Identifier (URI): Generic Syntax", "2005"),
    "RFC 3986",
    "RFC3986",
)
_add(
    StandardRef(
        "IETF", "RFC 7230", "HTTP/1.1 Message Syntax and Routing", "2014", "superseded", "RFC 9110"
    ),
    "RFC 7230",
    "RFC7230",
)
_add(StandardRef("IETF", "RFC 9110", "HTTP Semantics", "2022"), "RFC 9110", "RFC9110")

# ---------------------------------------------------------------------------
# IEEE standards
# ---------------------------------------------------------------------------

_add(StandardRef("IEEE", "754", "IEEE Standard for Floating-Point Arithmetic", "2019"), "IEEE 754")
_add(StandardRef("IEEE", "1003.1", "POSIX Base Specifications", "2024"), "IEEE 1003.1", "POSIX")
_add(StandardRef("IEEE", "802.3", "Ethernet", "2022"), "IEEE 802.3")
_add(StandardRef("IEEE", "1857", "Video Coding (AVS)", "2013"), "IEEE 1857")
_add(StandardRef("IEEE", "1857.2", "Advanced Audio Coding (AVS Audio)", "2013"), "IEEE 1857.2")

# ---------------------------------------------------------------------------
# AOM / AV1 / AV2
# ---------------------------------------------------------------------------

_add(StandardRef("AOM", "AV1", "AV1 Bitstream & Decoding Process Specification", "2019"), "AV1")
_add(StandardRef("AOM", "AV2", "AV2 Bitstream & Decoding Process Specification", ""), "AV2")

# ---------------------------------------------------------------------------
# Foundational ISO standards
# ---------------------------------------------------------------------------

_add(StandardRef("ISO", "639-1", "Language codes -- Part 1: Alpha-2 code", "2002"), "ISO 639-1")
_add(StandardRef("ISO", "639-2", "Language codes -- Part 2: Alpha-3 code", "1998"), "ISO 639-2")
_add(
    StandardRef(
        "ISO", "639-3", "Language codes -- Part 3: Alpha-3 code for comprehensive coverage", "2007"
    ),
    "ISO 639-3",
)
_add(StandardRef("ISO", "3166-1", "Country codes -- Part 1: Country codes", "2020"), "ISO 3166-1")
_add(
    StandardRef("ISO", "3166-2", "Country codes -- Part 2: Country subdivision code", "2020"),
    "ISO 3166-2",
)
_add(
    StandardRef("ISO", "8601-1", "Date and time -- Part 1: Basic rules", "2019"),
    "ISO 8601-1",
    "ISO 8601",
)
_add(StandardRef("ISO", "8601-2", "Date and time -- Part 2: Extensions", "2019"), "ISO 8601-2")
_add(StandardRef("ISO", "2382", "Information technology -- Vocabulary", "2015"), "ISO 2382")
_add(
    StandardRef("ISO", "80000-1", "Quantities and units -- Part 1: General", "2022"),
    "ISO 80000-1",
    "ISO 80000",
)
_add(
    StandardRef("ISO", "80000-2", "Quantities and units -- Part 2: Mathematics", "2019"),
    "ISO 80000-2",
)
_add(
    StandardRef(
        "ISO",
        "80000-13",
        "Quantities and units -- Part 13: Information science and technology",
        "2008",
    ),
    "ISO 80000-13",
)
_add(
    StandardRef(
        "ISO",
        "690",
        "Information and documentation -- Guidelines for bibliographic references",
        "2021",
    ),
    "ISO 690",
)
_add(
    StandardRef(
        "ISO",
        "10241-1",
        "Terminological entries in standards -- Part 1: General requirements",
        "2011",
    ),
    "ISO 10241-1",
)
_add(
    StandardRef(
        "ISO",
        "10241-2",
        "Terminological entries in standards -- Part 2: Adoption of standardized terminological entries",
        "2012",
    ),
    "ISO 10241-2",
)
_add(StandardRef("ISO", "704", "Terminology work -- Principles and methods", "2022"), "ISO 704")

# ---------------------------------------------------------------------------
# ISO/IEC Directives
# ---------------------------------------------------------------------------

_add(
    StandardRef("ISO/IEC", "Directives Part 1", "Procedures for the technical work", "2024"),
    "ISO/IEC DIRECTIVES PART 1",
)
_add(
    StandardRef(
        "ISO/IEC",
        "Directives Part 2",
        "Principles and rules for the structure and drafting of ISO and IEC documents",
        "2024",
    ),
    "ISO/IEC DIRECTIVES PART 2",
)

# ---------------------------------------------------------------------------
# Additional MPEG / ISO/IEC standards
# ---------------------------------------------------------------------------

_add(StandardRef("ISO/IEC", "11172-1", "MPEG-1 Systems", "1993"))
_add(StandardRef("ISO/IEC", "11172-2", "MPEG-1 Video", "1993"))
_add(StandardRef("ISO/IEC", "11172-3", "MPEG-1 Audio", "1993"))
_add(StandardRef("ISO/IEC", "13818-1", "MPEG-2 Systems (H.222.0)", "2022"))
_add(StandardRef("ISO/IEC", "13818-2", "MPEG-2 Video (H.262)", "2013"))
_add(StandardRef("ISO/IEC", "13818-7", "MPEG-2 Audio AAC", "2006"))
_add(StandardRef("ISO/IEC", "15444-1", "JPEG 2000 Core coding system", "2019"))
_add(StandardRef("ISO/IEC", "15444-2", "JPEG 2000 Extensions", "2021"))
_add(StandardRef("ISO/IEC", "15444-3", "Motion JPEG 2000", "2007"))
_add(StandardRef("ISO/IEC", "15444-12", "JPEG 2000 File format (JP2)", "2015"))
_add(StandardRef("ISO/IEC", "10918-1", "JPEG", "1994"), "JPEG")
_add(
    StandardRef(
        "ISO/IEC", "23001-7", "Common encryption in ISO base media file format files (CENC)", "2023"
    )
)
_add(StandardRef("ISO/IEC", "23000-19", "Common media application format (CMAF)", "2023"), "CMAF")
_add(StandardRef("ISO/IEC", "23009-1", "MPEG-DASH", "2022"), "DASH")
_add(
    StandardRef(
        "ISO/IEC", "14496-34", "MPEG-H Part 34: Carriage of MPEG-H 3D Audio in ISOBMFF", "2019"
    )
)
_add(
    StandardRef(
        "ISO/IEC", "23003-3", "MPEG-D Part 3: Unified Speech and Audio Coding (USAC)", "2020"
    )
)
_add(StandardRef("ISO/IEC", "23003-4", "MPEG-D Part 4: Dynamic Range Control (DRC)", "2020"))
_add(StandardRef("ISO/IEC", "23002-4", "MPEG-C Part 4: Video Tool Library (VTL)", "2018"))
_add(StandardRef("ISO/IEC", "21794-1", "JPEG Pleno Part 1: Framework", "2022"))
_add(StandardRef("ISO/IEC", "21794-2", "JPEG Pleno Light Field Coding", "2023"))
_add(StandardRef("ISO/IEC", "21794-5", "JPEG Pleno Point Cloud Coding", "2023"))
_add(StandardRef("ISO/IEC", "21778", "JSON data interchange syntax", "2017"), "JSON")
_add(
    StandardRef("ISO/IEC", "10646", "Universal Coded Character Set (UCS)", "2020"),
    "ISO/IEC 10646",
    "UCS",
)
_add(StandardRef("ISO/IEC", "8859-1", "Latin alphabet No. 1", "1998"), "ISO/IEC 8859-1", "LATIN-1")

# ---------------------------------------------------------------------------
# SMPTE standards
# ---------------------------------------------------------------------------

_add(StandardRef("SMPTE", "ST 2084", "High Dynamic Range EOTF (PQ)", "2014"), "SMPTE ST 2084", "PQ")
_add(
    StandardRef("SMPTE", "ST 2086", "Mastering Display Color Volume Metadata", "2018"),
    "SMPTE ST 2086",
)
_add(
    StandardRef(
        "SMPTE", "ST 2094-10", "Dynamic Metadata for Color Volume Transform — ATSC", "2016"
    ),
    "SMPTE ST 2094-10",
)
_add(
    StandardRef(
        "SMPTE", "ST 2094-40", "Dynamic Metadata for Color Volume Transform — SMPTE", "2016"
    ),
    "SMPTE ST 2094-40",
)
_add(
    StandardRef("SMPTE", "ST 2110-10", "Professional Media Over IP — System Timing", "2022"),
    "SMPTE ST 2110-10",
)
_add(
    StandardRef("SMPTE", "ST 2110-20", "Professional Media Over IP — Uncompressed Video", "2022"),
    "SMPTE ST 2110-20",
)
_add(
    StandardRef("SMPTE", "ST 2110-30", "Professional Media Over IP — PCM Audio", "2022"),
    "SMPTE ST 2110-30",
)
_add(StandardRef("SMPTE", "ST 274M", "1920x1080 Image Sample Structure", "2008"), "SMPTE ST 274M")
_add(StandardRef("SMPTE", "ST 296M", "1280x720 Image Sample Structure", "2012"), "SMPTE ST 296M")
_add(StandardRef("SMPTE", "ST 425-1", "3G-SDI", "2019"), "SMPTE ST 425-1")
_add(
    StandardRef("SMPTE", "RP 177", "Derivation of Basic Television Color Equations", "1993"),
    "SMPTE RP 177",
)

# ---------------------------------------------------------------------------
# ITU-R Recommendations
# ---------------------------------------------------------------------------

_add(
    StandardRef("ITU-R", "BT.601", "Studio encoding parameters for SDTV", "2011"),
    "BT.601",
    "ITU-R BT.601",
)
_add(StandardRef("ITU-R", "BT.709", "Parameter values for HDTV", "2015"), "BT.709", "ITU-R BT.709")
_add(
    StandardRef("ITU-R", "BT.2020", "Parameter values for UHDTV", "2015"),
    "BT.2020",
    "ITU-R BT.2020",
)
_add(
    StandardRef("ITU-R", "BT.2100", "Image parameter values for HDR TV", "2018"),
    "BT.2100",
    "ITU-R BT.2100",
)
_add(
    StandardRef("ITU-R", "BT.2390", "HDR TV production and display mastering", "2022"),
    "BT.2390",
    "ITU-R BT.2390",
)
_add(StandardRef("ITU-R", "BS.1770", "Loudness measurement", "2015"), "BS.1770", "ITU-R BS.1770")
_add(
    StandardRef("ITU-R", "BS.2051", "Advanced sound system for programme production", "2018"),
    "BS.2051",
    "ITU-R BS.2051",
)

# ---------------------------------------------------------------------------
# W3C Recommendations
# ---------------------------------------------------------------------------

_add(
    StandardRef("W3C", "XML 1.0", "Extensible Markup Language (XML) 1.0", "2008"), "XML 1.0", "XML"
)
_add(StandardRef("W3C", "HTML5", "HTML5", "2017"), "HTML5")
_add(StandardRef("W3C", "WebM", "WebM Container Guidelines", "2016"), "WEBM")
_add(StandardRef("W3C", "WebCodecs", "WebCodecs", "2023"), "WEBCODECS")
_add(
    StandardRef("W3C", "Media Source Extensions", "Media Source Extensions", "2016"),
    "MSE",
    "MEDIA SOURCE EXTENSIONS",
)
_add(
    StandardRef("W3C", "Encrypted Media Extensions", "Encrypted Media Extensions", "2017"),
    "EME",
    "ENCRYPTED MEDIA EXTENSIONS",
)
_add(StandardRef("W3C", "Web Audio API", "Web Audio API", "2021"), "WEB AUDIO API")
_add(
    StandardRef(
        "W3C", "WebRTC 1.0", "WebRTC 1.0: Real-Time Communication Between Browsers", "2021"
    ),
    "WEBRTC",
    "WEBRTC 1.0",
)
_add(
    StandardRef("W3C", "CSS Color Module Level 4", "CSS Color Module Level 4", "2022"),
    "CSS COLOR 4",
)

# ---------------------------------------------------------------------------
# ETSI standards
# ---------------------------------------------------------------------------

_add(StandardRef("ETSI", "TS 103 285", "DVB-DASH", "2022"), "ETSI TS 103 285")
_add(StandardRef("ETSI", "TS 101 154", "DVB-MPEG", "2019"), "ETSI TS 101 154")
_add(StandardRef("ETSI", "EN 300 468", "DVB-SI", "2022"), "ETSI EN 300 468")
_add(
    StandardRef("ETSI", "TS 102 366", "Digital Audio Compression AC-3, E-AC-3", "2017"),
    "ETSI TS 102 366",
)
_add(StandardRef("ETSI", "TS 126 346", "3GPP MBMS", "2020"), "ETSI TS 126 346")

# ---------------------------------------------------------------------------
# Dolby
# ---------------------------------------------------------------------------

_add(StandardRef("Dolby", "Dolby Vision", "Dolby Vision", "2020"), "DOLBY VISION")
_add(StandardRef("Dolby", "Dolby AC-4", "Dolby AC-4", "2017"), "DOLBY AC-4", "AC-4")
_add(StandardRef("Dolby", "Dolby Atmos", "Dolby Atmos", "2012"), "DOLBY ATMOS")

# ---------------------------------------------------------------------------
# Additional ISO standards (Photography, ICC, JPEG family)
# ---------------------------------------------------------------------------

_add(
    StandardRef("ISO", "12232", "Photography — Electronic still picture imaging", "2019"),
    "ISO 12232",
)
_add(
    StandardRef("ISO", "22028-1", "Photography — Extended colour encodings — Part 1", "2016"),
    "ISO 22028-1",
)
_add(
    StandardRef(
        "ISO",
        "15076-1",
        "ICC Color Management — Architecture, profile format, and data structure",
        "2010",
    ),
    "ISO 15076-1",
    "ICC",
)

# ---------------------------------------------------------------------------
# NIST standards (Federal Information Processing Standards + Special Pubs)
# ---------------------------------------------------------------------------

_add(
    StandardRef("NIST", "FIPS 46-3", "Data Encryption Standard (DES)", "1999"),
    "NIST FIPS 46-3",
    "FIPS 46-3",
    "DES",
)
_add(
    StandardRef("NIST", "FIPS 197", "Advanced Encryption Standard (AES)", "2001"),
    "NIST FIPS 197",
    "FIPS 197",
    "AES",
)
_add(
    StandardRef("NIST", "FIPS 180-4", "Secure Hash Standard (SHS)", "2015"),
    "NIST FIPS 180-4",
    "FIPS 180-4",
    "SHA",
)
_add(
    StandardRef("NIST", "FIPS 186-5", "Digital Signature Standard (DSS)", "2023"),
    "NIST FIPS 186-5",
    "FIPS 186-5",
    "DSS",
)
_add(
    StandardRef("NIST", "FIPS 202", "SHA-3 Standard: Permutation-Based Hash", "2015"),
    "NIST FIPS 202",
    "FIPS 202",
    "SHA-3",
)
_add(
    StandardRef("NIST", "SP 800-38D", "GCM for Confidentiality and Authentication", "2007"),
    "NIST SP 800-38D",
    "SP 800-38D",
)
_add(
    StandardRef("NIST", "SP 800-56A", "Key Establishment using DL Cryptography", "2018"),
    "NIST SP 800-56A",
    "SP 800-56A",
)
_add(
    StandardRef("NIST", "SP 800-57", "Recommendation for Key Management", "2020"),
    "NIST SP 800-57",
    "SP 800-57",
)
_add(
    StandardRef("NIST", "SP 800-90A", "Deterministic Random Bit Generators", "2015"),
    "NIST SP 800-90A",
    "SP 800-90A",
    "DRBG",
)

# ---------------------------------------------------------------------------
# 3GPP standards (TS = Technical Specification)
# ---------------------------------------------------------------------------

_add(
    StandardRef("3GPP", "TS 26.071", "AMR-NB speech codec", "2022"),
    "3GPP TS 26.071",
    "TS 26.071",
)
_add(
    StandardRef("3GPP", "TS 26.090", "AMR speech codec — Transcoding functions", "2022"),
    "3GPP TS 26.090",
    "TS 26.090",
)
_add(
    StandardRef("3GPP", "TS 26.101", "AMR-WB speech codec", "2022"),
    "3GPP TS 26.101",
    "TS 26.101",
)
_add(
    StandardRef(
        "3GPP", "TS 26.114", "IP Multimedia Subsystem (IMS) — Multimedia telephony", "2023"
    ),
    "3GPP TS 26.114",
    "TS 26.114",
)
_add(
    StandardRef("3GPP", "TS 26.116", "TV and multimedia services over 5G — Profiles", "2023"),
    "3GPP TS 26.116",
    "TS 26.116",
)
_add(
    StandardRef("3GPP", "TS 26.118", "VR media services over 3GPP", "2023"),
    "3GPP TS 26.118",
    "TS 26.118",
)
_add(
    StandardRef("3GPP", "TS 26.121", "Terminal acoustic characteristics", "2022"),
    "3GPP TS 26.121",
    "TS 26.121",
)
_add(
    StandardRef("3GPP", "TS 26.140", "Multimedia Messaging Service (MMS)", "2022"),
    "3GPP TS 26.140",
    "TS 26.140",
)
_add(
    StandardRef("3GPP", "TS 26.190", "AMR-WB+ speech codec — Transcoding functions", "2022"),
    "3GPP TS 26.190",
    "TS 26.190",
)
_add(
    StandardRef(
        "3GPP",
        "TS 26.244",
        "Transparent end-to-end packet-switched streaming (PSS) — 3GPP file format",
        "2023",
    ),
    "3GPP TS 26.244",
    "TS 26.244",
)
_add(
    StandardRef("3GPP", "TS 26.247", "Transparent end-to-end DASH", "2023"),
    "3GPP TS 26.247",
    "TS 26.247",
)
_add(
    StandardRef("3GPP", "TS 26.346", "Multimedia Broadcast/Multicast Service (MBMS)", "2022"),
    "3GPP TS 26.346",
    "TS 26.346",
)
_add(
    StandardRef("3GPP", "TS 26.503", "Immersive Voice and Video Services", "2023"),
    "3GPP TS 26.503",
    "TS 26.503",
)
_add(
    StandardRef("3GPP", "TS 38.300", "NR — Overall description — Stage 2 (5G NR)", "2023"),
    "3GPP TS 38.300",
    "TS 38.300",
    "5G NR",
)
_add(
    StandardRef("3GPP", "TS 23.501", "System Architecture for 5G System (5GS)", "2023"),
    "3GPP TS 23.501",
    "TS 23.501",
    "5GS",
)

# Pre-compiled patterns for parsing standard identifiers from free text.
_ISO_IEC_RE = re.compile(
    r"(?:ISO/?IEC)\s+(\d[\d.-]+)",
    re.IGNORECASE,
)
_ISO_PLAIN_RE = re.compile(
    r"(?<!\w)ISO\s+(\d[\d.-]+)",
    re.IGNORECASE,
)
_ITU_T_RE = re.compile(
    r"ITU[-\s]?T\s+((?:H|T|G|J|V|X|Y|Z)\.\d[\d.]*)",
    re.IGNORECASE,
)
_ITU_R_RE = re.compile(
    r"ITU[-\s]?R\s+((?:BT|BS|BR|BO)\.\d[\d.]*)",
    re.IGNORECASE,
)
_RFC_RE = re.compile(
    r"RFC\s*(\d{3,5})",
    re.IGNORECASE,
)
_IEEE_RE = re.compile(
    r"IEEE\s+([\d.]+)",
    re.IGNORECASE,
)
_SMPTE_RE = re.compile(
    r"SMPTE\s+((?:ST|RP)\s+[\d][\d.M-]*)",
    re.IGNORECASE,
)
_ETSI_RE = re.compile(
    r"ETSI\s+((?:TS|EN|ES|TR)\s+\d[\d ]*\d)",
    re.IGNORECASE,
)
_AOM_RE = re.compile(
    r"\b(AV[12])\b",
    re.IGNORECASE,
)


def lookup_standard(identifier: str) -> StandardRef | None:
    """Look up a standard by identifier with fuzzy matching.

    Accepts free-form text such as ``"ISO/IEC 14496-10:2022"`` or
    ``"RFC 2119"`` and tries to resolve it against the known database.

    Args:
        identifier: A document identifier string.

    Returns:
        The matching :class:`StandardRef`, or ``None``.
    """
    if not identifier:
        return None

    # Exact key match (case-insensitive)
    upper = identifier.strip().upper()
    if upper in KNOWN_STANDARDS:
        return KNOWN_STANDARDS[upper]

    # Strip trailing year / edition info for retry
    cleaned = re.sub(r"[:\s]+\d{4}.*$", "", upper).strip()
    if cleaned in KNOWN_STANDARDS:
        return KNOWN_STANDARDS[cleaned]

    # Try structured patterns
    for pattern, prefix_fn in (
        (_ISO_IEC_RE, lambda m: f"ISO/IEC {m.group(1)}"),
        (_ISO_PLAIN_RE, lambda m: f"ISO {m.group(1)}"),
        (_ITU_T_RE, lambda m: f"ITU-T {m.group(1)}"),
        (_ITU_R_RE, lambda m: f"ITU-R {m.group(1)}"),
        (_RFC_RE, lambda m: f"IETF RFC {m.group(1)}"),
        (_IEEE_RE, lambda m: f"IEEE {m.group(1)}"),
        (_SMPTE_RE, lambda m: f"SMPTE {m.group(1)}"),
        (_ETSI_RE, lambda m: f"ETSI {m.group(1)}"),
        (_AOM_RE, lambda m: f"AOM {m.group(1)}"),
    ):
        match = pattern.search(identifier)
        if match:
            key = prefix_fn(match).upper()
            if key in KNOWN_STANDARDS:
                return KNOWN_STANDARDS[key]

    return None


def extract_doc_identifier(text: str) -> str | None:
    """Extract the primary document identifier from a citation string.

    This parses the standards body and document number from free-form
    bibliography text.  It does **not** perform a database lookup.

    Args:
        text: Full text of a bibliography entry.

    Returns:
        Canonical identifier string (e.g. ``"ISO/IEC 14496-10"``) or
        ``None`` if no identifier could be extracted.
    """
    for pattern, prefix_fn in (
        (_ISO_IEC_RE, lambda m: f"ISO/IEC {m.group(1)}"),
        (_ISO_PLAIN_RE, lambda m: f"ISO {m.group(1)}"),
        (_ITU_T_RE, lambda m: f"ITU-T {m.group(1)}"),
        (_ITU_R_RE, lambda m: f"ITU-R {m.group(1)}"),
        (_RFC_RE, lambda m: f"RFC {m.group(1)}"),
        (_IEEE_RE, lambda m: f"IEEE {m.group(1)}"),
        (_SMPTE_RE, lambda m: f"SMPTE {m.group(1)}"),
        (_ETSI_RE, lambda m: f"ETSI {m.group(1)}"),
        (_AOM_RE, lambda m: f"{m.group(1)}"),
    ):
        match = pattern.search(text)
        if match:
            return prefix_fn(match)
    return None


def extract_cited_year(text: str) -> str | None:
    """Extract the cited year from a bibliography entry.

    Looks for patterns like ``:2022``, ``(2022)``, ``2022 edition``.

    Args:
        text: Full text of a bibliography entry.

    Returns:
        Four-digit year string or ``None``.
    """
    # :YYYY pattern (ISO style)
    m = re.search(r":(\d{4})\b", text)
    if m:
        return m.group(1)
    # (YYYY) pattern
    m = re.search(r"\((\d{4})\)", text)
    if m:
        return m.group(1)
    # ", YYYY" or ", YYYY," pattern
    m = re.search(r",\s*(\d{4})\b", text)
    if m:
        return m.group(1)
    m = re.search(r"\b((?:19|20)\d{2})\b", text)
    if m:
        return m.group(1)
    return None
