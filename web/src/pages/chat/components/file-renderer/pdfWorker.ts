/**
 * Eagerly configures pdf.js worker options and the text/annotation layer CSS.
 *
 * This MUST be a standalone module imported eagerly (not inside a lazy chunk).
 * react-pdf lazily initializes its worker, and when the worker setup lives
 * inside a `React.lazy`-loaded component the production build fails to spin up
 * the real worker (react-pdf#1843). Importing this module once at the top of
 * the (eager) FileRouter ensures `GlobalWorkerOptions.workerSrc` is set before
 * any <Document> mounts, in both dev and production.
 *
 * The `new URL('...', import.meta.url)` pattern is understood by Vite and
 * emits the worker as a separate chunk automatically.
 */
import { pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString();
