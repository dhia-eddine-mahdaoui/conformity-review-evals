"""Generate the synthetic technical file (three PDFs) for the demo.

Everything here is fictional: "Acme Widgets Ltd", "Example Test Laboratory",
the AW-200 power supply and the EXS standards do not exist.

The page layout is fixed on purpose: gold.yaml refers to these page numbers.
Planted facts (what the review should find):
  - Declared frequency (60 Hz) disagrees with the test report (50 Hz)
  - Touch current 0.62 mA exceeds the 0.5 mA limit although the lab wrote "Pass"
  - Insulation resistance is reported in GOhm while the limit is in MOhm
  - Nameplate (scanned page 11 of the test report) must be OCR'd for the current
  - Hazard H-06 has High residual risk and verification "Pending"
  - The test report never states an accreditation number
"""
import random
import sys
from pathlib import Path

import numpy as np
import pymupdf

W, H = 595, 842
ML = 50
OUT = Path(sys.argv[1]) if (__name__ == "__main__" and len(sys.argv) > 1) else Path(__file__).resolve().parents[1] / "data" / "techfile"

FILLER = [
    "The tests were carried out on a single production sample selected by the applicant.",
    "All measurements were performed in the laboratory climate-controlled area unless stated otherwise.",
    "The sample was examined for visible damage before and after each test sequence.",
    "Instruments used for the measurements are listed in the equipment table of this report.",
    "Where a requirement could not be evaluated, this is noted in the relevant clause.",
    "The results relate only to the item tested and do not extend to other production units.",
    "The applicant supplied the circuit diagrams and the bill of materials before testing started.",
    "Reference documents are identified by number and issue and are held in the technical file.",
    "Any deviation from the standard test method is recorded together with its justification.",
    "Measurement results are rounded to the number of significant digits shown in the tables.",
    "The enclosure is made of flame-retardant polycarbonate with a wall thickness of 2.5 mm.",
    "The product is intended for fixed installation in industrial control cabinets.",
    "Maintenance is limited to periodic visual inspection and cleaning of the ventilation openings.",
    "Training of installation personnel is the responsibility of the end user organisation.",
    "Records of the review are kept for the retention period defined by the quality system.",
]


class Pg:
    def __init__(self, doc, title, n, total, furniture=True):
        self.p = doc.new_page(width=W, height=H)
        self.y = 90
        if furniture:
            self.p.insert_text((ML, 40), title, fontsize=8, color=(0.4, 0.4, 0.4))
            self.p.draw_line((ML, 48), (W - ML, 48), color=(0.7, 0.7, 0.7))
            self.p.insert_text((ML, H - 30), "Fictional document for demonstration purposes", fontsize=7, color=(0.5, 0.5, 0.5))
            self.p.insert_text((W - ML - 60, H - 30), f"Page {n} of {total}", fontsize=8, color=(0.4, 0.4, 0.4))

    def wrap(self, text, size, width, font="helv"):
        lines, cur = [], ""
        for word in text.split():
            trial = (cur + " " + word).strip()
            if pymupdf.get_text_length(trial, fontname=font, fontsize=size) > width and cur:
                lines.append(cur)
                cur = word
            else:
                cur = trial
        return lines + ([cur] if cur else [])

    def h1(self, text):
        self.p.insert_text((ML, self.y), text, fontname="hebo", fontsize=16)
        self.y += 28

    def h2(self, text):
        self.y += 6
        self.p.insert_text((ML, self.y), text, fontname="hebo", fontsize=11)
        self.y += 18

    def para(self, text, size=10):
        for line in self.wrap(text, size, W - 2 * ML):
            self.p.insert_text((ML, self.y), line, fontsize=size)
            self.y += size + 3.5
        self.y += 8

    def kv(self, label, value):
        self.p.insert_text((ML, self.y), f"{label}: {value}", fontsize=10.5)
        self.y += 17

    def gap(self, n=10):
        self.y += n

    def table(self, widths, rows, size=8.5):
        x0 = ML
        for ri, row in enumerate(rows):
            wrapped = [self.wrap(str(c), size, w - 8) or [""] for c, w in zip(row, widths)]
            h = max(len(c) for c in wrapped) * (size + 3) + 8
            x = x0
            for c, w, lines in zip(row, widths, wrapped):
                rect = pymupdf.Rect(x, self.y, x + w, self.y + h)
                self.p.draw_rect(rect, color=(0, 0, 0), width=0.6, fill=(0.9, 0.92, 0.95) if ri == 0 else None)
                for li, line in enumerate(lines):
                    self.p.insert_text((x + 4, self.y + 4 + size + li * (size + 3) - 1), line,
                                       fontname="hebo" if ri == 0 else "helv", fontsize=size)
                x += w
            self.y += h
        self.y += 14

    def filler(self, rng, k=4):
        self.para(" ".join(rng.sample(FILLER, k)))


def scan_page(doc, lines, title="EQUIPMENT NAMEPLATE - PHOTOCOPY", footer="Test report TR-AW200-001 - annex scan",
              rotate=False, noise=9, skew=0):
    """Render a page to a noisy grayscale bitmap and insert it as the only content.

    rotate=True stores the bitmap turned by 90 degrees on a landscape page, as when a
    sheet is fed sideways into a scanner."""
    tmp = pymupdf.open()
    t = tmp.new_page(width=W, height=H)
    morph = (pymupdf.Point(W / 2, H / 2), pymupdf.Matrix(skew)) if skew else None  # small tilt, as a crooked sheet
    t.insert_text((ML, 60), title, fontname="cobo", fontsize=15, morph=morph)
    y = 130
    t.draw_rect(pymupdf.Rect(ML, 100, W - ML, 100 + 40 * len(lines) + 30), width=1.5, morph=morph)
    for line in lines:
        t.insert_text((ML + 20, y + 10), line, fontname="cour", fontsize=17, morph=morph)
        y += 40
    t.insert_text((ML, H - 30), footer, fontname="cour", fontsize=9)
    pix = t.get_pixmap(dpi=130, colorspace=pymupdf.csGRAY)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).astype(np.float32)
    rs = np.random.RandomState(3)
    arr = np.clip(arr * 0.9 + 12 + rs.normal(0, noise, arr.shape), 0, 255).astype(np.uint8)
    if rotate:
        arr = np.ascontiguousarray(np.rot90(arr))
    noisy = pymupdf.Pixmap(pymupdf.csGRAY, arr.shape[1], arr.shape[0], arr.tobytes(), False)
    page = doc.new_page(width=H, height=W) if rotate else doc.new_page(width=W, height=H)
    page.insert_image(page.rect, stream=noisy.tobytes("png"))


def declaration(path):
    rng = random.Random(11)
    d = pymupdf.open()
    t = "Declaration of Conformity AW-200"
    p = Pg(d, t, 1, 4)
    p.h1("Declaration of Conformity")
    p.para("Issued under the sole responsibility of the manufacturer named below.")
    p.kv("Manufacturer", "Acme Widgets Ltd")
    p.kv("Address", "12 Example Road, Sampletown, Exampleland")
    p.kv("Product", "Industrial Power Supply")
    p.kv("Model", "AW-200")
    p.kv("Rated voltage", "230 V AC")
    p.kv("Rated frequency", "60 Hz")
    p.kv("Declaration number", "DoC-AW200-2025-01")
    p.gap()
    p.para("The object of the declaration described above is in conformity with the relevant requirements listed on the following pages.")
    p = Pg(d, t, 2, 4)
    p.h1("Applicable standards")
    p.para("Conformity was assessed against the following documents:")
    p.para("EXS 1000-1:2020 - Safety of power supply equipment - General requirements")
    p.para("EXS 1000-2-5:2019 - Safety of power supply equipment - Particular requirements for industrial units")
    p.para("EXS 2000-3:2018 - Electromagnetic compatibility - Emission limits")
    p.filler(rng, 3)
    p = Pg(d, t, 3, 4)
    p.h1("Statement and signature")
    p.para("The manufacturer declares that the product named in this declaration satisfies the requirements of the standards listed above.")
    p.gap(20)
    p.kv("Signed for and on behalf of", "Acme Widgets Ltd")
    p.kv("Name and function", "A. Example, Head of Compliance")
    p.kv("Place", "Sampletown")
    p.kv("Date of issue", "2025-03-14")
    p = Pg(d, t, 4, 4)
    p.h1("Technical documentation")
    p.para("The technical file is held by the manufacturer and comprises the test report, the risk assessment and the declaration of conformity.")
    p.filler(rng, 4)
    d.set_metadata({"title": "Declaration of Conformity (fictional)"})
    d.save(path, garbage=3, deflate=True)


def test_report(path):
    rng = random.Random(5)
    N = 14
    t = "Test report TR-AW200-001 - Acme Widgets AW-200"
    d = pymupdf.open()
    p = Pg(d, t, 1, N)
    p.h1("Test Report TR-AW200-001")
    p.kv("Applicant", "Acme Widgets Ltd")
    p.kv("Product", "Industrial Power Supply, model AW-200")
    p.kv("Test laboratory", "Example Test Laboratory")
    p.kv("Date of report", "2025-02-27")
    p.gap()
    p.para("This report documents the safety tests carried out on one sample of the product identified above.")
    p = Pg(d, t, 2, N)
    p.h1("Contents and scope")
    p.para("1 General information  /  2 Ratings  /  3 Equipment  /  4 Conditions  /  5 Results  /  6 Conclusion")
    p.filler(rng, 5)
    p.filler(rng, 4)
    p = Pg(d, t, 3, N)
    p.h1("Product description and ratings")
    p.para("The ratings below are taken from the product data sheet and were confirmed against the nameplate.")
    p.table([200, 150, 145], [
        ["Parameter", "Value", "Unit"],
        ["Model designation", "AW-200", "-"],
        ["Rated input voltage", "230", "V"],
        ["Rated frequency", "50", "Hz"],
        ["Rated input current", "2.5", "A"],
        ["Rated output", "24 V DC / 5 A", "-"],
        ["Input voltage tolerance", "10", "%"],
    ])
    p.filler(rng, 2)
    p = Pg(d, t, 4, N)
    p.h1("Test equipment")
    p.table([150, 110, 130, 105], [
        ["Instrument", "Type", "Range", "Calibration due"],
        ["High-voltage tester", "HT-5000", "0 to 5000 V", "2026-01"],
        ["Insulation tester", "IT-100", "0.1 MOhm to 10 GOhm", "2026-03"],
        ["Leakage current meter", "LC-20", "0 to 20 mA", "2025-11"],
        ["Temperature logger", "TL-8", "-20 to 200 C", "2026-02"],
    ])
    p.filler(rng, 3)
    p = Pg(d, t, 5, N)
    p.h1("Test conditions")
    p.kv("Ambient temperature", "23 C")
    p.kv("Relative humidity", "45 %")
    p.kv("Supply used for tests", "230 V, 50 Hz")
    p.gap()
    p.filler(rng, 5)
    p = Pg(d, t, 6, N)
    p.h1("Summary of results")
    p.para("Detailed results for each test are given on the following pages. Each result is compared with the requirement of the applicable standard.")
    p.filler(rng, 5)
    p = Pg(d, t, 7, N)
    p.h1("Insulation resistance")
    p.para("Measured with 500 V DC applied for one minute after humidity preconditioning.")
    p.table([170, 60, 55, 120, 90], [
        ["Test point", "Measured", "Unit", "Requirement", "Result"],
        ["Insulation resistance, input to output", "0.25", "GOhm", ">= 100 MOhm", "Pass"],
        ["Insulation resistance, input to earth", "480", "MOhm", ">= 100 MOhm", "Pass"],
    ])
    p.filler(rng, 2)
    p = Pg(d, t, 8, N)
    p.h1("Dielectric strength")
    p.table([150, 60, 55, 65, 95, 70], [
        ["Test point", "Applied", "Unit", "Duration", "Observation", "Result"],
        ["Dielectric strength, input to output", "1500", "V AC", "60 s", "No breakdown", "Pass"],
        ["Dielectric strength, input to earth", "1500", "V AC", "60 s", "No breakdown", "Pass"],
    ])
    p.filler(rng, 3)
    p = Pg(d, t, 9, N)
    p.h1("Touch current")
    p.para("Measured with the measuring network of the standard, supply at rated voltage and frequency.")
    p.table([190, 60, 50, 110, 85], [
        ["Condition", "Measured", "Unit", "Requirement", "Result"],
        ["Touch current, normal condition", "0.31", "mA", "<= 0.5 mA", "Pass"],
        ["Touch current, single fault condition", "0.62", "mA", "<= 0.5 mA", "Pass"],
    ])
    p.filler(rng, 3)
    p = Pg(d, t, 10, N)
    p.h1("Temperature rise")
    p.para("Temperature rise was determined after thermal equilibrium at maximum load.")
    p.table([210, 70, 50, 100, 65], [
        ["Measuring point", "Measured", "Unit", "Requirement", "Result"],
        ["Temperature rise, transformer winding", "36", "K", "<= 40 K", "Pass"],
        ["Temperature rise, enclosure surface", "28", "K", "<= 40 K", "Pass"],
        ["Temperature rise, output terminals", "31", "K", "<= 40 K", "Pass"],
    ])
    p.filler(rng, 2)
    scan_page(d, ["MODEL: AW-200", "RATED VOLTAGE: 230 V AC", "RATED FREQUENCY: 50 Hz",
                  "RATED CURRENT: 2.5 A", "OUTPUT: 24 V DC", "S/N: 000417"])  # page 11
    p = Pg(d, t, 12, N)
    p.h1("Photo documentation")
    p.para("Photographs of the sample and the test set-up are retained by the laboratory and available on request.")
    p.filler(rng, 5)
    p = Pg(d, t, 13, N)
    p.h1("Measurement uncertainty")
    p.para("The expanded uncertainty is stated with a coverage factor of 2 giving a confidence level of approximately 95 %.")
    p.filler(rng, 5)
    p = Pg(d, t, 14, N)
    p.h1("Conclusion")
    p.para("The sample was tested as described. The results are listed on pages 7 to 10.")
    p.gap(14)
    p.kv("Prepared by", "Example Test Laboratory")
    p.kv("Test engineer", "B. Sample")
    p.kv("Date", "2025-02-27")
    d.set_metadata({"title": "Test report (fictional)"})
    d.save(path, garbage=3, deflate=True)


def risk_assessment(path):
    rng = random.Random(23)
    N = 10
    t = "Risk assessment RA-AW200 - Acme Widgets AW-200"
    d = pymupdf.open()
    p = Pg(d, t, 1, N)
    p.h1("Risk Assessment RA-AW200")
    p.kv("Product", "Industrial Power Supply")
    p.kv("Model", "AW-200")
    p.kv("Manufacturer", "Acme Widgets Ltd")
    p.kv("Revision", "B")
    p = Pg(d, t, 2, N)
    p.h1("Methodology")
    p.para("Each hazard is rated for initial risk and for residual risk after the control measures are applied. Ratings are Low, Medium or High.")
    p.filler(rng, 5)
    p = Pg(d, t, 3, N)
    p.h1("Intended use and users")
    p.filler(rng, 6)
    hdr = ["ID", "Hazard", "Initial", "Control measure", "Residual", "Verification"]
    wd = [35, 135, 45, 170, 50, 60]
    p = Pg(d, t, 4, N)
    p.h1("Hazard register (1 of 2)")
    p.table(wd, [hdr,
                 ["H-01", "Electric shock from accessible live parts", "High", "Reinforced insulation and earthed enclosure", "Low", "V-01"],
                 ["H-02", "Overheating of the power stage", "Medium", "Thermal cut-out and derating curve", "Low", "V-02"],
                 ["H-03", "Fire from component failure", "Medium", "Flame-retardant materials", "Low", "V-03"]])
    p = Pg(d, t, 5, N)
    p.h1("Hazard register (2 of 2)")
    p.table(wd, [hdr,
                 ["H-04", "Stored energy at the output terminals", "Low", "Bleeder resistor", "Low", "V-04"],
                 ["H-05", "Sharp edges on the enclosure", "Low", "Deburring and edge protection", "Low", "V-05"],
                 ["H-06", "Enclosure instability when wall mounted", "High", "Mounting bracket rated for three times the weight", "High", "Pending"],
                 ["H-07", "Acoustic noise", "Low", "None required", "Low", "V-07"]])
    p = Pg(d, t, 6, N)
    p.h1("Residual risk summary")
    p.para("The residual risks after control measures are summarised by the project team and reviewed with the product manager.")
    p.filler(rng, 5)
    p = Pg(d, t, 7, N)
    p.h1("Information for users")
    p.filler(rng, 6)
    p = Pg(d, t, 8, N)
    p.h1("Verification records")
    p.para("Verification records V-01 to V-05 and V-07 are filed with the design documentation.")
    p.filler(rng, 4)
    p = Pg(d, t, 9, N)
    p.h1("Review history")
    p.filler(rng, 5)
    p = Pg(d, t, 10, N)
    p.h1("Approval")
    p.kv("Prepared by", "C. Placeholder")
    p.kv("Approved by", "A. Example, Head of Compliance")
    d.set_metadata({"title": "Risk assessment (fictional)"})
    d.save(path, garbage=3, deflate=True)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    declaration(OUT / "declaration_of_conformity.pdf")
    test_report(OUT / "test_report.pdf")
    risk_assessment(OUT / "risk_assessment.pdf")
    print("wrote", ", ".join(sorted(p.name for p in OUT.glob("*.pdf"))))
