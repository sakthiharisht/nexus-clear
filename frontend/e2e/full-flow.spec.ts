import { test, expect } from "@playwright/test";
import path from "node:path";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// M9 accept criterion: a full run on a defective packet, from upload
// through reviewer resolution to an attested packet, in fixture/replay
// mode (no live API key - every model call below resolves from the
// real committed eval/fixtures/model_cache/, same as the backend's own
// test suite). "Defective" here is the exact scenario
// backend/tests/api/test_m8_acceptance.py already proves end to end
// against the real API: clean-1's real documents (license holder
// "Christopher Lee") uploaded against an intake profile that says
// "John Smyth" - a genuine name mismatch the Investigator can't
// auto-resolve on its own, needing a human reviewer.

const PACKET_DIR = path.resolve(__dirname, "../../eval/fixtures/packets/clean-1");
const SCREENSHOT_DIR = path.resolve(__dirname, "../../docs/screenshots");
const REVIEWER_TOKEN = "demo-reviewer-token";

const SLOTS = ["license", "coi", "cv", "education", "w9"] as const;

test.beforeAll(() => {
  fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
  for (const slot of SLOTS) {
    const file = path.join(PACKET_DIR, `${slot}.pdf`);
    if (!fs.existsSync(file)) {
      throw new Error(
        `${file} not found - run \`uv run python -m app.eval.generator.build\` from backend/ first`,
      );
    }
  }
});

test("defective packet: upload through reviewer resolution to an attested packet", async ({
  page,
}) => {
  test.setTimeout(5 * 60 * 1000);

  await page.goto("/");
  await page.getByLabel("Legal name").fill("John Smyth");
  await page.getByLabel("NPI").fill("1000000004");
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "01-create-case.png") });
  await page.getByRole("button", { name: "Create case" }).click();

  await expect(page.getByText("Checklist")).toBeVisible();

  for (const slot of SLOTS) {
    const row = page.locator("tr", { hasText: slot });
    await row.locator('input[type="file"]').setInputFiles(path.join(PACKET_DIR, `${slot}.pdf`));
    await expect(row.getByText("uploaded")).toBeVisible({ timeout: 15_000 });
  }
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "02-checklist-complete.png") });

  await page.getByRole("button", { name: "Run" }).click();
  await expect(page.getByText(/findings,.*sent to the reviewer queue/)).toBeVisible({
    timeout: 30_000,
  });
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "03-run-result.png") });

  await page.getByRole("navigation").getByRole("link", { name: "Findings" }).click();
  await expect(page.getByText("Readiness score")).toBeVisible();
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "04-findings-report.png") });

  // The name mismatch between the intake profile and clean-1's real
  // documents shows up on more than one rule (license holder name, COI
  // insured name) - each escalates to its own queue item. Resolve every
  // pending one, not just the first, since attest blocks on ANY open item.
  await page.getByRole("navigation").getByRole("link", { name: "Reviewer queue" }).click();
  await page.getByLabel("Reviewer token").fill(REVIEWER_TOKEN);

  // Resolving an item can shift its row's position on reload (no
  // stable sort key before the backend fix above existed), so walk
  // positionally and skip anything already resolved rather than
  // re-filtering by "pending" text each time.
  let screenshotted = false;
  const rows = page.locator("table.table tbody tr");
  for (let i = 0; i < (await rows.count()); i++) {
    await rows.nth(i).getByRole("button", { name: "view" }).click();
    if (await page.getByText("already resolved").isVisible()) continue;

    await expect(page.getByText("confidence:")).toBeVisible();
    if (!screenshotted) {
      await page.screenshot({ path: path.join(SCREENSHOT_DIR, "05-review-detail.png") });
      screenshotted = true;
    }

    await page.getByLabel("Decision").selectOption("override");
    await page.getByLabel("New status").selectOption("pass");
    await page.getByLabel("Note").fill("Confirmed same person via a secondary ID check.");
    await page.getByRole("button", { name: "Resolve" }).click();
    await expect(page.getByText("already resolved")).not.toBeVisible();
  }

  // Pre-M9 fix #2: attest refuses until the case is run again after a
  // review resolution - go back and run once more before attesting.
  await page.getByRole("navigation").getByRole("link", { name: "Case" }).click();
  await page.getByRole("button", { name: "Run" }).click();
  await expect(page.getByText(/findings,.*sent to the reviewer queue/)).toBeVisible({
    timeout: 30_000,
  });

  await page.getByRole("navigation").getByRole("link", { name: "Packet & confirmation" }).click();
  await expect(page.getByText("This is not CAQH attestation")).toBeVisible();
  await expect(page.getByText("Not yet confirmed")).toBeVisible();
  await page.getByLabel("Confirmed by").fill("reviewer-1");
  await page.getByLabel("Typed name").fill("Reviewer One");
  await page.getByLabel(/I confirm this packet/).check();
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "06-attest-form.png") });
  await page.getByRole("button", { name: "Confirm packet is accurate" }).click();

  await expect(page.getByText(/confirmed - packet hash/)).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("CAQH-style")).toBeVisible();
  await expect(page.getByText(/"holder_name": "Christopher Lee"/)).toBeVisible();
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "07-attested-packet.png") });
});
