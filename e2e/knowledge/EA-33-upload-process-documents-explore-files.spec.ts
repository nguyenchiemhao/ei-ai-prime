// EA-33 (KB-02): writes the sample files of the exploratory run (Chrome DevTools) into a folder.
// It is not a test: it is skipped unless EA33_EXPLORE_DIR is set, and it needs no stack.
//   EA33_EXPLORE_DIR=.work/EA-33/explore-files npm run e2e -- e2e/knowledge/EA-33-upload-process-documents-explore-files.spec.ts
// Files: text PDF (3 pages), scanned PDF, broken PDF, DOCX, MD, Vietnamese TXT (NFC and NFD), TXT with a
// BOM, UTF-16 TXT, setup.exe, old.doc, table.xlsx, a 52 428 801-byte big.pdf and a `many/` folder of 25
// small TXT files. All upload-able names carry the marker `qa-EA33-explore`.
import fs from "node:fs";
import path from "node:path";
import { test } from "@playwright/test";
import {
  LIMIT_BYTES,
  OVERTIME,
  OVERTIME_VI,
  buildDocx,
  buildMd,
  buildPdf,
  buildScannedPdf,
  filler,
  fillerVi,
  randomJunk,
} from "../support/ea33";

const target = process.env.EA33_EXPLORE_DIR;

test("EA-33 exploratory sample files", async () => {
  test.skip(!target, "set EA33_EXPLORE_DIR to write the sample files");
  const dir = path.resolve(target as string);
  fs.mkdirSync(path.join(dir, "many"), { recursive: true });
  const write = (name: string, data: Buffer | string): void =>
    fs.writeFileSync(path.join(dir, name), data);
  const mark = "qa-EA33-explore";
  const vi = fillerVi("zqvi", 4000);
  write(
    `${mark}-text.pdf`,
    buildPdf([filler("zqpg1", 900), filler("zqpg2", 900), filler("zqpg3", 900)]),
  );
  write(`${mark}-scan.pdf`, buildScannedPdf(2));
  write(`${mark}-broken.pdf`, randomJunk(4096));
  write(`${mark}-policy.docx`, buildDocx(OVERTIME, { pages: 4 }));
  write(`${mark}-policy-vi.docx`, buildDocx(OVERTIME_VI, { vi: true, form: "NFD" }));
  write(`${mark}-policy.md`, buildMd(OVERTIME));
  write(`${mark}-vi-nfc.txt`, vi.normalize("NFC"));
  write(`${mark}-vi-nfd.txt`, vi.normalize("NFD"));
  write(`${mark}-bom.txt`, Buffer.concat([Buffer.from([0xef, 0xbb, 0xbf]), Buffer.from(vi)]));
  write(
    `${mark}-utf16.txt`,
    Buffer.concat([Buffer.from([0xff, 0xfe]), Buffer.from(vi, "utf16le")]),
  );
  write("setup.exe", randomJunk(1024));
  write("old.doc", randomJunk(1024));
  write("table.xlsx", randomJunk(1024));
  const handle = fs.openSync(path.join(dir, `${mark}-big.pdf`), "w");
  fs.ftruncateSync(handle, LIMIT_BYTES + 1);
  fs.closeSync(handle);
  for (let index = 0; index < 25; index++) {
    write(
      path.join("many", `${mark}-many-${String(index).padStart(2, "0")}.txt`),
      filler(`zqm${index}`, 600),
    );
  }
});
