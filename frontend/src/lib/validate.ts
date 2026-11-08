// Client-side mirrors of the backend validators (the backend re-checks everything).
const D = [
  [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
  [3, 4, 0, 1, 2, 8, 9, 5, 6, 7], [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
  [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3], [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
  [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
];
const P = [
  [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
  [8, 9, 1, 6, 0, 4, 3, 5, 2, 7], [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
  [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
];

export function verhoeff(num: string): boolean {
  let c = 0;
  const digits = num.split("").reverse();
  for (let i = 0; i < digits.length; i++) c = D[c][P[i % 8][Number(digits[i])]];
  return c === 0;
}

export function validateAadhaar(v: string): string | null {
  const n = v.replace(/[\s-]/g, "");
  if (!/^\d{12}$/.test(n)) return "Aadhaar number must be exactly 12 digits";
  if (/^[01]/.test(n)) return "Aadhaar number cannot start with 0 or 1";
  if (!verhoeff(n)) return "This Aadhaar number is not valid. Please check it.";
  return null;
}

export function validatePan(v: string): string | null {
  return /^[A-Z]{5}[0-9]{4}[A-Z]$/.test(v.toUpperCase().replace(/\s/g, ""))
    ? null
    : "PAN must look like ABCDE1234F (5 letters, 4 digits, 1 letter)";
}

export function validatePhone(v: string): string | null {
  const d = v.replace(/\D/g, "");
  const local = d.length === 12 && d.startsWith("91") ? d.slice(2) : d.length === 11 && d.startsWith("0") ? d.slice(1) : d;
  return /^[6-9]\d{9}$/.test(local) ? null : "Enter a valid 10-digit mobile number";
}

export async function sniffFile(file: File, allowPdf: boolean): Promise<string | null> {
  if (file.size > 5 * 1024 * 1024) return "File must be 5 MB or smaller";
  const head = new Uint8Array(await file.slice(0, 8).arrayBuffer());
  const isJpg = head[0] === 0xff && head[1] === 0xd8 && head[2] === 0xff;
  const isPng = head[0] === 0x89 && head[1] === 0x50 && head[2] === 0x4e && head[3] === 0x47;
  const isPdf = head[0] === 0x25 && head[1] === 0x50 && head[2] === 0x44 && head[3] === 0x46;
  if (isJpg || isPng || (allowPdf && isPdf)) return null;
  return allowPdf ? "Upload a JPG, PNG or PDF file" : "Upload a JPG or PNG photo";
}
