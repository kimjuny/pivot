/**
 * Incrementally extract known string fields from a JSON text stream.
 *
 * TypeScript twin of the backend ``StreamingFieldExtractor`` (see
 * ``server/app/orchestration/react/json_stream.py``).  The backend now
 * forwards tool-call ``arguments`` JSON fragments verbatim; this extractor
 * scans them char-by-char and surfaces the in-progress value of the large
 * text fields (``content`` / ``diff`` / ``old_string`` / ``new_string``)
 * so the UI can render live ``+N`` line counters as the LLM writes.
 *
 * Properties mirrored from the Python original:
 *  * Incremental -- each ``feed()`` only processes its own characters.
 *  * Schema-aware -- callers pass the set of field names they care about.
 *  * Escape-aware -- JSON string escapes (``\n``, ``\uXXXX`` ...) are
 *    decoded on the fly, so the surfaced value is plain text.
 *  * Independent of validation -- it does not verify well-formedness; the
 *    finalized ``arguments`` payload is the source of truth.
 */

const SCANNING = 0; // outside any string, looking for the next `"`
const READING_NAME = 1; // between the quotes of a potential field name
const AFTER_NAME = 2; // saw closing quote of name; expecting `:` then `"`
const IN_STRING = 3; // inside a *known* string field, decoding
const IN_OTHER_STRING = 4; // inside a string we don't care about

const SIMPLE_ESCAPES: Record<string, string> = {
  '"': '"',
  '\\': '\\',
  '/': '/',
  n: '\n',
  t: '\t',
  r: '\r',
  b: '\b',
  f: '\f',
};

/**
 * One extracted fragment for a known string field. Concatenating all
 * fragments for a field (across feeds) yields its decoded value so far.
 */
export interface FieldDelta {
  fieldName: string;
  delta: string;
  /** True once the field's closing quote has been seen. */
  isFinal: boolean;
}

/**
 * Streaming JSON string-field extractor.
 *
 * Typical usage (one instance per tool call, kept alive across feeds):
 *
 * ```ts
 * const extractor = new StreamingFieldExtractor(["content", "diff"]);
 * for (const chunk of rawArgumentFragments) {
 *   for (const delta of extractor.feed(chunk)) {
 *     accumulate(delta);
 *   }
 * }
 * ```
 */
export class StreamingFieldExtractor {
  private readonly fieldNames: Set<string>;
  private state: number = SCANNING;
  private nameBuf = '';
  private currentField = '';
  private escapePending = false;
  private unicodePending = false;
  private unicodeBuf = '';
  private completedFields = new Set<string>();
  private pendingFieldForValue = '';
  private afterNameSeenColon = false;

  constructor(fieldNames: Iterable<string>) {
    this.fieldNames = new Set(fieldNames);
  }

  /** Consume one stream chunk; return deltas decoded from it. */
  feed(chunk: string): FieldDelta[] {
    if (!chunk) {
      return [];
    }
    const deltas: FieldDelta[] = [];
    for (const ch of chunk) {
      this.consume(ch, deltas);
    }
    return deltas;
  }

  /**
   * Flush trailing state when the stream has ended.
   *
   * If we were mid-field, emit a final empty delta so callers can settle.
   */
  markComplete(): FieldDelta[] {
    const deltas: FieldDelta[] = [];
    if (this.state === IN_STRING && this.currentField) {
      const fieldName = this.currentField;
      this.completedFields.add(fieldName);
      this.currentField = '';
      this.state = SCANNING;
      deltas.push({ fieldName, delta: '', isFinal: true });
    }
    this.nameBuf = '';
    this.pendingFieldForValue = '';
    this.afterNameSeenColon = false;
    return deltas;
  }

  private consume(ch: string, deltas: FieldDelta[]): void {
    switch (this.state) {
      case IN_STRING:
        this.consumeInString(ch, deltas);
        break;
      case IN_OTHER_STRING:
        this.consumeInOtherString(ch);
        break;
      case READING_NAME:
        this.consumeReadingName(ch);
        break;
      case AFTER_NAME:
        this.consumeAfterName(ch);
        break;
      default:
        this.consumeScanning(ch);
        break;
    }
  }

  private consumeScanning(ch: string): void {
    if (ch === '"') {
      this.nameBuf = '';
      this.state = READING_NAME;
    }
  }

  private consumeReadingName(ch: string): void {
    if (ch === '"') {
      const name = this.nameBuf;
      this.nameBuf = '';
      if (this.fieldNames.has(name) && !this.completedFields.has(name)) {
        // Commit only when we see the `:` separator.
        this.pendingFieldForValue = name;
        this.afterNameSeenColon = false;
        this.state = AFTER_NAME;
      } else {
        this.pendingFieldForValue = '';
        this.state = SCANNING;
      }
    } else {
      this.nameBuf += ch;
    }
  }

  private consumeAfterName(ch: string): void {
    if (ch === ':') {
      this.afterNameSeenColon = true;
      return;
    }
    if (ch === '"') {
      if (this.afterNameSeenColon) {
        this.currentField = this.pendingFieldForValue;
        this.pendingFieldForValue = '';
        this.afterNameSeenColon = false;
        this.state = IN_STRING;
      } else {
        // No `:` -- the matched name was a string value, not a field name.
        this.pendingFieldForValue = '';
        this.afterNameSeenColon = false;
        this.state = IN_OTHER_STRING;
      }
      return;
    }
    if (!this.afterNameSeenColon && ',{}[]'.includes(ch)) {
      this.pendingFieldForValue = '';
      this.state = SCANNING;
    }
  }

  private consumeInOtherString(ch: string): void {
    if (this.unicodePending) {
      this.unicodeBuf += ch;
      if (this.unicodeBuf.length >= 4) {
        this.unicodeBuf = '';
        this.unicodePending = false;
      }
      return;
    }
    if (this.escapePending) {
      this.escapePending = false;
      if (ch === 'u') {
        this.unicodePending = true;
        this.unicodeBuf = '';
      }
      return;
    }
    if (ch === '\\') {
      this.escapePending = true;
      return;
    }
    if (ch === '"') {
      this.state = SCANNING;
    }
  }

  private consumeInString(ch: string, deltas: FieldDelta[]): void {
    const fieldName = this.currentField;
    if (this.unicodePending) {
      this.unicodeBuf += ch;
      if (this.unicodeBuf.length >= 4) {
        const code = safeHex(this.unicodeBuf);
        this.unicodeBuf = '';
        this.unicodePending = false;
        if (code !== null) {
          deltas.push({
            fieldName,
            delta: String.fromCodePoint(code),
            isFinal: false,
          });
        }
      }
      return;
    }
    if (this.escapePending) {
      this.escapePending = false;
      const simple = SIMPLE_ESCAPES[ch];
      if (simple !== undefined) {
        deltas.push({ fieldName, delta: simple, isFinal: false });
      } else if (ch === 'u') {
        this.unicodePending = true;
        this.unicodeBuf = '';
      }
      return;
    }
    if (ch === '\\') {
      this.escapePending = true;
      return;
    }
    if (ch === '"') {
      this.completedFields.add(fieldName);
      this.currentField = '';
      this.state = SCANNING;
      deltas.push({ fieldName, delta: '', isFinal: true });
      return;
    }
    deltas.push({ fieldName, delta: ch, isFinal: false });
  }
}

function safeHex(text: string): number | null {
  const code = parseInt(text, 16);
  return Number.isFinite(code) ? code : null;
}
