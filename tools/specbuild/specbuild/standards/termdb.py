"""External terminology database for auto-importing standard terms.

Provides a curated set of terms from key standards vocabularies (ISO 2382
IT vocabulary, ISO/IEC video coding terms, etc.) that can be auto-imported
into a specification's Terms and definitions section.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from specbuild.utils import HEADING_RE

if TYPE_CHECKING:
    from bs4 import BeautifulSoup


TERM_DATABASES: dict[str, dict[str, str]] = {
    "iso2382": {
        "bit": "binary digit; either of the digits 0 and 1 when used in the binary numeration system",
        "byte": "string of eight bits treated as a unit",
        "pixel": "smallest addressable element in a display space",
        "codec": "device or program capable of encoding or decoding a digital data stream or signal",
        "bitstream": "binary representation of a coded signal",
        "syntax": "set of rules governing the structure of a bitstream or language",
        "semantics": "meaning associated with syntactic constructs",
        "encoder": "device or program that encodes",
        "decoder": "device or program that decodes",
        "algorithm": "finite ordered set of well-defined rules for the solution of a problem",
        "parameter": "variable that is given a value for a specific application",
        "buffer": "storage area that compensates for a difference in rate of flow of data",
        "flag": "variable that indicates a state or condition",
        "frame": "complete image in a sequence of images",
        "field": "set of all odd-numbered or all even-numbered lines of a frame",
        "resolution": "number of pixels per unit length or number of samples per unit time",
        "quantization": "process of representing a continuous or high-resolution value by a discrete or lower-resolution value",
        "entropy": "measure of the information content of a message",
        "luminance": "photometric quantity corresponding to the brightness of light",
        "chrominance": "colour information in a video signal, separate from luminance",
    },
    "video-coding": {
        "picture": "coded representation of a single frame or field",
        "slice": "spatially distinct region of a picture that is independently decodable",
        "macroblock": "basic coding unit in some video coding standards, typically 16x16 luma samples",
        "coding tree unit": "largest coding unit in a quadtree-based video coding structure",
        "coding unit": "rectangular region of samples used as the basic unit for coding decisions",
        "prediction unit": "region for which a single prediction mode is applied",
        "transform unit": "region to which a transform is applied for coding residual data",
        "motion vector": "two-dimensional vector used for inter-picture prediction",
        "reference picture": "previously decoded picture used for prediction of subsequent pictures",
        "intra prediction": "prediction of a block from reconstructed samples within the same picture",
        "inter prediction": "prediction of a block from samples in a different, previously decoded picture",
        "residual": "difference between an original block and its prediction",
        "transform coefficient": "scalar quantity considered to be an element of the result of a transform applied to residual data",
        "quantization parameter": "variable controlling the step size of quantization",
        "entropy coding": "lossless coding that uses statistical properties to compress data",
        "CABAC": "context-adaptive binary arithmetic coding; an entropy coding method",
        "deblocking filter": "filter applied across block boundaries to reduce blocking artifacts",
        "SAO": "sample adaptive offset; a filtering method applied after deblocking",
        "ALF": "adaptive loop filter; a Wiener-based filtering method applied after SAO",
        "NAL unit": "network abstraction layer unit; a packet of coded data including a header",
        "VCL": "video coding layer; the part of the bitstream containing coded picture data",
        "profile": "defined subset of the syntax, semantics, and features of a coding standard",
        "level": "set of constraints on coding parameters such as picture size and bitrate",
        "tier": "additional classification within a level, typically indicating real-time capability",
        "DPB": "decoded picture buffer; buffer holding reference pictures for inter prediction",
        "CPB": "coded picture buffer; buffer model used to verify conformance of bitstream timing",
        "HRD": "hypothetical reference decoder; a model specifying timing constraints",
        "SEI": "supplemental enhancement information; metadata carried alongside coded pictures",
        "VPS": "video parameter set; high-level syntax structure for multi-layer configurations",
        "SPS": "sequence parameter set; syntax structure containing parameters for a coded sequence",
        "PPS": "picture parameter set; syntax structure containing parameters for a coded picture",
    },
    "image-coding": {
        "tile": "rectangular region of an image that is independently coded",
        "subband": "portion of the frequency spectrum resulting from a filter bank decomposition",
        "wavelet": "mathematical function used in multiresolution signal analysis",
        "codeblock": "basic unit of entropy coding in wavelet-based image coders",
        "precinct": "grouping of codeblocks for packetization purposes",
        "code-stream": "ordered sequence of bytes conforming to a coding syntax",
        "component": "one of the arrays (e.g., Y, Cb, Cr) that make up an image",
        "bit-plane": "one bit from each coefficient in a codeblock, forming a binary array",
    },
    "point-cloud": {
        "point cloud": "set of data points in 3D space, each with position (x, y, z) and optional attributes",
        "voxel": "volume element; a value on a regular grid in three-dimensional space",
        "occupancy": "binary indication of whether a 3D location contains a point",
        "attribute": "property associated with a point (e.g., color, normal, reflectance)",
        "geometry": "positional information (x, y, z coordinates) of points in a point cloud",
        "octree": "hierarchical tree structure that recursively subdivides 3D space into eight octants",
        "level of detail": "representation of a point cloud at a specific resolution or density",
        "normal vector": "unit vector perpendicular to the local surface at a point",
        "bounding box": "axis-aligned minimum enclosing rectangular parallelepiped",
        "patch": "connected group of points projected onto a 2D plane for coding",
        "geometry image": "2D image representing the 3D geometry of a point cloud patch",
        "attribute image": "2D image representing attribute values of a point cloud patch",
    },
    "mesh-coding": {
        "mesh": "collection of vertices, edges, and faces defining the shape of a 3D object",
        "vertex": "point in 3D space that forms a corner of a polygon in a mesh",
        "edge": "line segment connecting two vertices in a mesh",
        "face": "planar polygon defined by an ordered set of vertices and edges",
        "triangle mesh": "mesh composed entirely of triangular faces",
        "texture map": "2D image mapped onto the surface of a 3D mesh",
        "UV coordinates": "2D texture coordinates mapping mesh vertices to texture image positions",
        "normal map": "texture storing per-pixel surface normal directions for lighting calculations",
        "displacement map": "texture encoding surface displacement along normals",
        "mesh simplification": "process of reducing the number of polygons while preserving visual quality",
        "subdivision surface": "smooth surface defined by iterative refinement of a control mesh",
    },
    "gaussian-splat": {
        "gaussian splat": "3D representation using anisotropic Gaussian functions for novel view synthesis",
        "splat": "ellipsoidal primitive defined by position, covariance, opacity, and spherical harmonics",
        "splatting": "rendering technique that projects 3D Gaussians onto the image plane",
        "spherical harmonics": "basis functions on the sphere used to represent view-dependent color",
        "covariance matrix": "3x3 matrix defining the shape and orientation of a Gaussian ellipsoid",
        "opacity": "scalar value controlling the transparency of a Gaussian primitive",
        "alpha blending": "compositing technique combining semi-transparent Gaussians front-to-back",
        "point-based rendering": "rendering paradigm using point primitives instead of polygons",
        "tile-based rasterization": "rendering approach that processes Gaussians per screen tile",
        "densification": "process of adding new Gaussian primitives to under-reconstructed regions",
    },
}


def get_term_definition(term: str, databases: list[str] | None = None) -> str | None:
    """Look up a term in the terminology databases.

    Args:
        term: Term to look up (case-insensitive).
        databases: List of database names to search. If None, searches all.

    Returns:
        Definition string, or None if not found.
    """
    term_lower = term.lower().strip()
    dbs = databases or list(TERM_DATABASES.keys())

    for db_name in dbs:
        db = TERM_DATABASES.get(db_name, {})
        if term_lower in db:
            return db[term_lower]
    return None


def import_terms_soup(
    soup: BeautifulSoup,
    databases: list[str] | None = None,
) -> int:
    """Import external term definitions into the Terms section.

    For each `<dfn>` or `<dt>` in the Terms and definitions section
    that lacks a definition, attempts to auto-fill from the terminology
    databases.

    Returns the number of terms imported.
    """
    terms_section = _find_terms_section(soup)
    if terms_section is None:
        return 0

    count = 0

    for dt in terms_section.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        if dd and dd.get_text(strip=True):
            continue

        term_text = dt.get_text(strip=True)
        definition = get_term_definition(term_text, databases)
        if definition:
            if dd is None:
                dd = soup.new_tag("dd")
                dt.insert_after(dd)

            from bs4 import NavigableString

            dd.clear()
            dd.append(NavigableString(definition))
            dd["class"] = dd.get("class", []) + ["auto-imported"]
            dd["data-source"] = "specbuild-termdb"
            count += 1

    if count:
        logging.info(f"Auto-imported {count} term definition(s) from external databases")
    return count


def suggest_missing_terms_soup(
    soup: BeautifulSoup,
    databases: list[str] | None = None,
) -> list[dict[str, str]]:
    """Suggest terms used in the document that should be defined.

    Scans the document body for terms that appear in the terminology
    databases but are not in the Terms and definitions section.

    Returns a list of suggestion dicts.
    """
    terms_section = _find_terms_section(soup)
    defined_terms: set[str] = set()

    if terms_section:
        for dt in terms_section.find_all("dt"):
            defined_terms.add(dt.get_text(strip=True).lower())
        for dfn in terms_section.find_all("dfn"):
            defined_terms.add(dfn.get_text(strip=True).lower())

    all_terms: dict[str, str] = {}
    dbs = databases or list(TERM_DATABASES.keys())
    for db_name in dbs:
        for term, defn in TERM_DATABASES.get(db_name, {}).items():
            all_terms[term] = defn

    body = soup.find("body")
    if body is None:
        return []

    body_text = body.get_text().lower()
    suggestions = []

    for term, defn in all_terms.items():
        if term in defined_terms:
            continue
        pattern = re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
        if pattern.search(body_text):
            suggestions.append(
                {
                    "term": term,
                    "definition": defn,
                    "message": f"Term '{term}' is used in the document but not defined.",
                }
            )

    if suggestions:
        logging.info(f"Found {len(suggestions)} undefined term(s) that could be imported")
    return suggestions


def register_external_terms(db_name: str, terms: dict[str, str]) -> None:
    """Register an external term dictionary into the TERM_DATABASES.

    Args:
        db_name: Identifier for the database (e.g. "my-org-glossary").
        terms: Mapping of lowercase term → definition string.
    """
    TERM_DATABASES[db_name] = {k.lower(): v for k, v in terms.items()}
    logging.info(f"Registered external term database '{db_name}' with {len(terms)} term(s)")


def load_terms_from_tbx(path: str) -> dict[str, str]:
    """Load terms from a TBX (TermBase eXchange / ISO 30042) XML file.

    Parses ``<conceptEntry>`` elements and extracts the first ``<term>``
    and ``<definition>`` found under each concept.

    Args:
        path: Path to the ``.tbx`` or ``.xml`` file.

    Returns:
        Dict mapping lowercase term → definition string.
    """
    import xml.etree.ElementTree as ET

    terms: dict[str, str] = {}
    try:
        tree = ET.parse(path)
    except Exception as exc:
        logging.warning(f"Failed to parse TBX file '{path}': {exc}")
        return {}

    root = tree.getroot()
    ns = root.tag.split("}")[0] + "}" if root.tag.startswith("{") else ""

    for concept in root.iter(f"{ns}conceptEntry"):
        term_text = ""
        definition_text = ""
        for lang_sec in concept.iter(f"{ns}langSec"):
            for term_sec in lang_sec.iter(f"{ns}termSec"):
                t = term_sec.find(f"{ns}term")
                if t is not None and t.text:
                    term_text = t.text.strip()
                    break
            if term_text:
                break
        for def_el in concept.iter(f"{ns}definition"):
            if def_el.text:
                definition_text = def_el.text.strip()
                break
        if term_text and definition_text:
            terms[term_text.lower()] = definition_text

    logging.info(f"Loaded {len(terms)} term(s) from TBX file '{path}'")
    return terms


def load_terms_from_yaml(path: str) -> dict[str, str]:
    """Load terms from a YAML file mapping term → definition.

    The YAML file should be a flat mapping at the top level, e.g.::

        coding unit: A block of samples that is coded as a unit.
        prediction block: A rectangular block used for intra/inter prediction.

    Args:
        path: Path to the ``.yaml`` or ``.yml`` file.

    Returns:
        Dict mapping lowercase term → definition string.
    """
    try:
        import yaml  # type: ignore[import]
    except ImportError:
        logging.warning("PyYAML not installed; cannot load YAML term database")
        return {}

    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        logging.warning(f"Failed to load YAML term file '{path}': {exc}")
        return {}

    if not isinstance(data, dict):
        logging.warning(
            f"YAML term file '{path}' must be a flat mapping; got {type(data).__name__}"
        )
        return {}

    terms = {str(k).lower(): str(v) for k, v in data.items()}
    logging.info(f"Loaded {len(terms)} term(s) from YAML file '{path}'")
    return terms


def _find_terms_section(soup: BeautifulSoup):
    """Find the Terms and definitions section."""
    terms_re = re.compile(r"(?i)^(?:\d+(?:\.\d+)*\s+)?terms\s+(and|,)\s+definitions$")
    for tag in soup.find_all(HEADING_RE):
        text = tag.get_text(" ", strip=True)
        if terms_re.match(text):
            return tag.find_parent("section")
    return None
