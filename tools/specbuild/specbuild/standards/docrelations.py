"""Document relations metadata for standards documents.

Captures relationships between documents (supersedes, amends, is-part-of, etc.)
and provides utilities to extract them from HTML meta tags, inject them into
``<head>`` as ``<link>`` / ``<meta>`` elements, and render a human-readable list.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

#: Supported relation types and their corresponding HTML ``<link rel>`` values.
_RELATION_LINK_REL: dict[str, str] = {
    "supersedes": "predecessor",
    "superseded-by": "successor",
    "amends": "predecessor",
    "is-amended-by": "successor",
    "part-of": "collection",
    "has-part": "item",
    "corrects": "predecessor",
    "is-corrected-by": "successor",
}

#: Meta name prefixes recognised by :func:`extract_relations_from_soup`.
_META_PREFIX = "doc-"


@dataclass
class DocumentRelation:
    """A single directed relationship between this document and another.

    Args:
        relation_type: One of ``"supersedes"``, ``"superseded-by"``,
            ``"amends"``, ``"is-amended-by"``, ``"part-of"``,
            ``"has-part"``, ``"corrects"``, ``"is-corrected-by"``.
        docid: Document identifier, e.g. ``"ISO/IEC 14496-10:2022"``.
        url: Optional URL to the related document.
        description: Optional free-text description of the relationship.
    """

    relation_type: str
    docid: str
    url: str | None = None
    description: str | None = None


@dataclass
class DocumentRelations:
    """Collection of :class:`DocumentRelation` objects for a document.

    Examples::

        rels = DocumentRelations()
        rels.add("supersedes", "ISO/IEC 14496-10:2022")
        rels.add("amends", "ISO/IEC 23094-1:2020/Amd 1:2023", url="https://example.com")
    """

    relations: list[DocumentRelation] = field(default_factory=list)

    def add(self, relation_type: str, docid: str, **kwargs) -> None:
        """Append a new relation.

        Args:
            relation_type: The relation type string.
            docid: The related document identifier.
            **kwargs: Optional keyword arguments forwarded to
                :class:`DocumentRelation` (``url``, ``description``).
        """
        self.relations.append(DocumentRelation(relation_type=relation_type, docid=docid, **kwargs))

    def by_type(self, relation_type: str) -> list[DocumentRelation]:
        """Return all relations of a given type.

        Args:
            relation_type: The relation type to filter by.

        Returns:
            A list of matching :class:`DocumentRelation` objects (may be empty).
        """
        return [r for r in self.relations if r.relation_type == relation_type]

    def to_dict(self) -> dict:
        """Serialise to a plain dict suitable for JSON output.

        Returns:
            Dict with a single ``"relations"`` key containing a list of
            per-relation dicts.
        """
        return {
            "relations": [
                {k: v for k, v in vars(r).items() if v is not None} for r in self.relations
            ]
        }

    @classmethod
    def from_dict(cls, data: dict) -> DocumentRelations:
        """Deserialise from a dict produced by :meth:`to_dict`.

        Args:
            data: Dict with a ``"relations"`` key.

        Returns:
            A new :class:`DocumentRelations` instance.
        """
        obj = cls()
        for item in data.get("relations", []):
            obj.add(
                item["relation_type"],
                item["docid"],
                url=item.get("url"),
                description=item.get("description"),
            )
        return obj

    @classmethod
    def from_toml_config(cls, config: dict) -> DocumentRelations:
        """Build a :class:`DocumentRelations` from a ``[standards.relations]`` TOML section.

        Expected TOML structure::

            [standards.relations]
            supersedes = ["ISO/IEC 14496-10:2022"]
            amends = [{docid = "ISO/IEC 23094-1:2020", url = "https://example.com"}]

        Each value may be a list of bare strings (docid only) or dicts with
        ``docid``, ``url``, and/or ``description`` keys.

        Args:
            config: The ``[standards.relations]`` section dict.

        Returns:
            A new :class:`DocumentRelations` instance.
        """
        obj = cls()
        for rel_type, entries in config.items():
            if not isinstance(entries, list):
                entries = [entries]
            for entry in entries:
                if isinstance(entry, str):
                    obj.add(rel_type, entry)
                elif isinstance(entry, dict):
                    docid = entry.get("docid")
                    if docid:
                        extras = {k: v for k, v in entry.items() if k != "docid"}
                        obj.add(rel_type, docid, **extras)
        return obj


# ---------------------------------------------------------------------------
# HTML extraction
# ---------------------------------------------------------------------------


def extract_relations_from_soup(soup: BeautifulSoup) -> DocumentRelations:
    """Extract document relations from ``<meta>`` tags in *soup*.

    Recognised tag patterns::

        <meta name="doc-supersedes" content="ISO/IEC 14496-10:2022">
        <meta name="doc-amends" content="ISO/IEC 23094-1:2020/Amd 1:2023">
        <meta name="doc-superseded-by" content="...">

    The portion after the ``doc-`` prefix is used as the relation type.

    Args:
        soup: Parsed HTML document.

    Returns:
        :class:`DocumentRelations` populated from any matching ``<meta>`` tags.
    """
    rels = DocumentRelations()
    for tag in soup.find_all("meta"):
        name = tag.get("name", "")
        if not name.startswith(_META_PREFIX):
            continue
        rel_type = name[len(_META_PREFIX) :]
        content = tag.get("content", "").strip()
        if content:
            rels.add(rel_type, content)
    return rels


# ---------------------------------------------------------------------------
# HTML injection
# ---------------------------------------------------------------------------


def inject_relations_metadata(soup: BeautifulSoup, relations: DocumentRelations) -> int:
    """Inject document relations as ``<link>`` and ``<meta>`` tags in ``<head>``.

    For each relation a ``<meta name="doc-<type>" content="<docid>">`` tag is
    added.  Additionally, when a matching ``<link rel>`` mapping exists (see
    :data:`_RELATION_LINK_REL`) a ``<link>`` tag is also injected.

    Args:
        soup: Parsed HTML document to modify in-place.
        relations: The relations to inject.

    Returns:
        Number of tags injected (``<meta>`` + ``<link>`` combined).
    """
    head = soup.find("head")
    if head is None:
        return 0

    injected = 0
    for rel in relations.relations:
        meta_tag = soup.new_tag("meta")
        meta_tag["name"] = f"{_META_PREFIX}{rel.relation_type}"
        meta_tag["content"] = rel.docid
        head.append(meta_tag)
        injected += 1

        link_rel = _RELATION_LINK_REL.get(rel.relation_type)
        if link_rel:
            link_tag = soup.new_tag("link")
            link_tag["rel"] = link_rel
            href = rel.url or f"urn:docid:{rel.docid}"
            link_tag["href"] = href
            link_tag["title"] = rel.docid
            head.append(link_tag)
            injected += 1

    return injected


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------


def render_relations_html(relations: DocumentRelations) -> str:
    """Render a human-readable HTML ``<section>`` listing document relations.

    Args:
        relations: The relations to render.

    Returns:
        An HTML string (empty string if there are no relations).
    """
    if not relations.relations:
        return ""

    parts: list[str] = [
        "<section class='doc-relations'>",
        "<h2>Document Relations</h2>",
        "<ul>",
    ]
    for rel in relations.relations:
        label = rel.relation_type.replace("-", " ").title()
        if rel.url:
            ref = f"<a href='{rel.url}'>{rel.docid}</a>"
        else:
            ref = rel.docid
        desc = f" — {rel.description}" if rel.description else ""
        parts.append(f"<li><strong>{label}:</strong> {ref}{desc}</li>")
    parts += ["</ul>", "</section>"]
    return "\n".join(parts)
