"""Render synthetic documents as PDFs (reportlab) or degraded scan images
(Pillow), per SPEC.md section 10.

Content (title + text lines) and rendering backend (clean PDF vs degraded
raster scan) are deliberately separate: a document's *content* depends on
what was uploaded (e.g. D09 puts CV content in the license slot) and is
independent of *how* it's rendered (e.g. D10 renders that same slot as an
illegible scan). Keeping them orthogonal means any content can go through
either backend — packets.py picks one of each rather than this module
offering only the four pre-paired combinations it happened to need first.

Degraded scans avoid depending on a PDF-to-image rasterizer (e.g.
poppler): Pillow draws the same text directly onto a raster canvas, then
applies the degradation filters.

reportlab's `Canvas(..., invariant=1)` is what makes PDF output byte-
identical across runs with the same content (verified empirically before
relying on it here — reportlab otherwise embeds a wall-clock
CreationDate, which would break the "deterministic from seed" M2 accept
criterion).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

from app.eval.generator.provider import ProviderSpec


@dataclass(frozen=True)
class DocumentContent:
    title: str
    lines: list[str]


def license_content(provider: ProviderSpec) -> DocumentContent:
    return DocumentContent(
        "Texas Licensed Professional Counselor",
        [
            f"Holder name: {provider.license_holder_name}",
            f"License number: {provider.license_number}",
            f"License type: {provider.license_type}",
            f"Status: {provider.license_status}",
            f"Issue date: {provider.license_issue_date.isoformat()}",
            f"Expiration date: {provider.license_expiration_date.isoformat()}",
            f"Issuing board: {provider.issuing_board}",
        ],
    )


def coi_content(provider: ProviderSpec) -> DocumentContent:
    return DocumentContent(
        "Certificate of Malpractice Insurance",
        [
            f"Insured: {provider.coi_insured_name}",
            f"Carrier: {provider.coi_carrier}",
            f"Policy number: {provider.coi_policy_number}",
            f"Effective date: {provider.coi_effective_date.isoformat()}",
            f"Expiration date: {provider.coi_expiration_date.isoformat()}",
            f"Per occurrence: ${provider.coi_per_occurrence:,.0f}",
            f"Aggregate: ${provider.coi_aggregate:,.0f}",
        ],
    )


def cv_content(provider: ProviderSpec, injection_text: str | None = None) -> DocumentContent:
    lines = [f"Name: {provider.legal_name}", "", "Work history:"]
    for pos in provider.positions:
        end = pos.end.isoformat() if pos.end else "present"
        lines.append(f"  {pos.title}, {pos.employer} ({pos.start.isoformat()} - {end})")
    if injection_text:
        lines += ["", "Additional notes:", f"  {injection_text}"]
    return DocumentContent("Curriculum Vitae", lines)


def education_content(provider: ProviderSpec) -> DocumentContent:
    return DocumentContent(
        "Degree / Transcript",
        [
            f"Name: {provider.legal_name}",
            f"Institution: {provider.education_institution}",
            f"Degree: {provider.education_degree}",
            f"Conferred: {provider.education_date.isoformat()}",
        ],
    )


def w9_content(provider: ProviderSpec) -> DocumentContent:
    return DocumentContent(
        "Form W-9 (synthetic)",
        [
            f"Name: {provider.legal_name}",
            f"Business name: {provider.w9_business_name}",
            f"TIN: {provider.w9_tin}  (synthetic, clearly-invalid format)",
            "Signed: yes",
        ],
    )


def write_pdf(path: Path, content: DocumentContent) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=LETTER, invariant=1)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(72, 740, content.title)
    c.setFont("Helvetica", 11)
    y = 710
    for line in content.lines:
        c.drawString(72, y, line)
        y -= 18
    c.showPage()
    c.save()


def write_scan_image(
    path: Path,
    content: DocumentContent,
    *,
    rotate_degrees: float = 0,
    blur_radius: float = 0,
    noise_amount: int = 0,
    contrast_factor: float = 1.0,
    add_shadow: bool = False,
    seed: int = 0,
) -> None:
    """A degraded "scanned" rendering of the same content write_pdf would
    show — used for the illegible-scan defect (D10) and the benign
    rotated-scan variation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = 850, 1100
    image = Image.new("L", (width, height), color=255)
    draw = ImageDraw.Draw(image)
    draw.text((40, 30), content.title, fill=0)
    y = 70
    for line in content.lines:
        draw.text((40, y), line, fill=0)
        y += 24

    if add_shadow:
        # A soft diagonal gradient darkening one corner, like a scanner lid
        # shadow — deterministic (no randomness), just a fixed gradient.
        shadow = Image.new("L", (width, height), color=0)
        shadow_draw = ImageDraw.Draw(shadow)
        for x in range(width):
            alpha = int(60 * (x / width))
            shadow_draw.line([(x, 0), (x, height)], fill=alpha)
        image = Image.composite(Image.new("L", (width, height), 0), image, shadow)

    if contrast_factor != 1.0:
        image = ImageEnhance.Contrast(image).enhance(contrast_factor)

    if noise_amount:
        # Deterministic pseudo-noise from a fixed seed, not system randomness.
        rng = random.Random(seed)
        pixels = image.load()
        assert pixels is not None
        for _ in range(noise_amount):
            x = rng.randrange(width)
            y_noise = rng.randrange(height)
            pixels[x, y_noise] = rng.choice([0, 255])

    if blur_radius:
        image = image.filter(ImageFilter.GaussianBlur(radius=blur_radius))

    if rotate_degrees:
        image = image.rotate(rotate_degrees, expand=True, fillcolor=255)

    image.convert("RGB").save(path, format="PNG")


def render_coi(provider: ProviderSpec, path: Path) -> None:
    write_pdf(path, coi_content(provider))


def render_cv(provider: ProviderSpec, path: Path, injection_text: str | None = None) -> None:
    write_pdf(path, cv_content(provider, injection_text))


def render_education(provider: ProviderSpec, path: Path) -> None:
    write_pdf(path, education_content(provider))


def render_w9(provider: ProviderSpec, path: Path) -> None:
    write_pdf(path, w9_content(provider))
