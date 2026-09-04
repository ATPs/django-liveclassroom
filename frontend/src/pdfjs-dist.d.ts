declare module "pdfjs-dist/build/pdf.mjs" {
  type Viewport = { width: number; height: number };
  type PdfPage = {
    getViewport(options: { scale: number }): Viewport;
    render(options: { canvasContext: CanvasRenderingContext2D; viewport: Viewport }): { promise: Promise<void> };
  };
  type PdfDocument = {
    numPages: number;
    getPage(pageNumber: number): Promise<PdfPage>;
    destroy(): Promise<void>;
  };

  export const GlobalWorkerOptions: { workerSrc: string };
  export function getDocument(options: { data: Uint8Array }): { promise: Promise<PdfDocument> };
}
