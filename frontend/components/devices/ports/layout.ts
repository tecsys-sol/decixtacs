import type { Port, PortForm } from "./types";

/** Size of a port cage in faceplate units (1U chassis ≈ 96 units high). */
export const PORT_SIZE: Record<PortForm, { w: number; h: number }> = {
  qsfpdd: { w: 34, h: 22 },
  qsfp: { w: 31, h: 20 },
  sfp: { w: 20, h: 14 },
  rj45: { w: 19, h: 16 },
  virtual: { w: 18, h: 14 },
};

export interface PlacedPort {
  port: Port;
  x: number;
  y: number;
  w: number;
  h: number;
  /** LED sits above the top row and below the bottom row, like on real front panels */
  ledAbove: boolean;
  label: string;
}

export interface PortGroup {
  x: number;
  y: number;
  w: number;
  h: number;
  title: string | null;
}

export interface FaceplateLayout {
  width: number;
  height: number;
  ports: PlacedPort[];
  groups: PortGroup[];
}

const EAR = 26; // rack ear width
const LEFT = EAR + 96; // room for the vendor/model plate
const RIGHT_PAD = EAR + 18;
const COL_GAP = 4;
const ROW_GAP = 12;
const GROUP_GAP = 20;
const MAX_ROW_WIDTH = 1180;

/** "xe-0/1/3" -> "3", "Ethernet12" -> "12", "et-0/0/1:2" -> "1" */
export function portNumber(name: string): string {
  const base = name.split(":")[0];
  const m = /(\d+)(?!.*\d)/.exec(base);
  return m ? m[1] : name;
}

/** "xe-0/1/3" -> "0/1" (FPC/PIC); used to split ports without a device type into line cards. */
function slotOf(name: string): string {
  const m = /(\d+(?:\/\d+)*)\/\d+(?::\d+)?$/.exec(name);
  return m ? m[1] : "";
}

/** Label each port with the number that changes across its block ("Ethernet12/1" -> "12", "xe-0/1/3" -> "3"). */
function blockLabels(ports: Port[]): string[] {
  const nums = ports.map((p) => (p.name.split(":")[0].match(/\d+/g) ?? []).map(Number));
  const len = Math.max(0, ...nums.map((n) => n.length));
  let pos = len - 1;
  while (pos > 0 && new Set(nums.map((n) => n[pos])).size <= 1) pos--;
  return ports.map((p, i) => (nums[i].length && ports.length > 1 && nums[i][pos] !== undefined ? String(nums[i][pos]) : portNumber(p.name)));
}

function rowsFor(form: PortForm, n: number): number {
  if (form === "qsfp" || form === "qsfpdd") return n > 8 ? 2 : 1;
  return n > 6 ? 2 : 1;
}

/**
 * Arrange ports like a front panel: consecutive ports of the same form factor form a block;
 * blocks with many ports use two rows numbered column-first (0 top, 1 bottom, 2 top ...).
 * Management ports go to a block on the right. Blocks wrap onto further rows ("line cards").
 */
export function layoutFaceplate(ports: Port[], uHeight = 1): FaceplateLayout {
  const data = ports.filter((p) => !p.mgmt);
  const mgmt = ports.filter((p) => p.mgmt);
  const blocks: { form: PortForm; ports: Port[]; title: string | null }[] = [];
  for (const p of data) {
    const key = p.in_template ? p.form : `${p.form}|${slotOf(p.name)}`;
    const last = blocks[blocks.length - 1];
    const lastKey = last ? (last.ports[0].in_template ? last.form : `${last.form}|${slotOf(last.ports[0].name)}`) : null;
    if (last && lastKey === key) last.ports.push(p);
    else blocks.push({ form: p.form, ports: [p], title: p.in_template ? null : slotOf(p.name) ? `slot ${slotOf(p.name)}` : null });
  }
  if (mgmt.length) blocks.push({ form: mgmt[0].form, ports: mgmt, title: "MGMT" });

  // measure blocks
  const measured = blocks.map((b) => {
    const size = PORT_SIZE[b.form] ?? PORT_SIZE.sfp;
    const rows = rowsFor(b.form, b.ports.length);
    const cols = Math.ceil(b.ports.length / rows);
    const pairGap = b.form === "sfp" || b.form === "rj45" ? 2 : COL_GAP;
    return {
      ...b,
      size,
      rows,
      cols,
      pairGap,
      w: cols * size.w + (cols - 1) * pairGap,
      h: rows * size.h + (rows - 1) * ROW_GAP,
    };
  });

  // wrap blocks into rows of the faceplate
  const lines: (typeof measured)[] = [];
  let cur: typeof measured = [];
  let curW = 0;
  for (const b of measured) {
    const add = (cur.length ? GROUP_GAP : 0) + b.w;
    if (cur.length && curW + add > MAX_ROW_WIDTH - LEFT - RIGHT_PAD) {
      lines.push(cur);
      cur = [];
      curW = 0;
    }
    cur.push(b);
    curW += (cur.length > 1 ? GROUP_GAP : 0) + b.w;
  }
  if (cur.length) lines.push(cur);

  const LINE_PAD = 26; // space for LEDs and numbers above/below a line
  const lineHeights = lines.map((l) => Math.max(...l.map((b) => b.h)) + 2 * LINE_PAD);
  const contentH = lineHeights.reduce((a, b) => a + b, 0);
  const height = Math.max(96 * Math.max(1, uHeight), contentH + 16);
  const widest = Math.max(0, ...lines.map((l) => l.reduce((a, b, i) => a + b.w + (i ? GROUP_GAP : 0), 0)));
  const width = Math.max(560, LEFT + widest + RIGHT_PAD);

  const placed: PlacedPort[] = [];
  const groups: PortGroup[] = [];
  let y0 = (height - contentH) / 2;
  lines.forEach((line, li) => {
    const lh = lineHeights[li];
    let x = LEFT;
    for (const b of line) {
      const top = y0 + (lh - b.h) / 2;
      groups.push({ x, y: top, w: b.w, h: b.h, title: b.title });
      const labels = blockLabels(b.ports);
      b.ports.forEach((p, i) => {
        const col = Math.floor(i / b.rows);
        const row = i % b.rows;
        placed.push({
          port: p,
          x: x + col * (b.size.w + b.pairGap),
          y: top + row * (b.size.h + ROW_GAP),
          w: b.size.w,
          h: b.size.h,
          ledAbove: row === 0,
          label: labels[i],
        });
      });
      x += b.w + GROUP_GAP;
    }
    y0 += lh;
  });
  return { width, height, ports: placed, groups };
}
