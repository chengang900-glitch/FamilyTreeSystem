import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Space, Spin } from 'antd'
import type { PDFDocumentProxy, PDFDocumentLoadingTask, RenderTask } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

// CMap和标准字体均由构建器输出到本站，禁止预览请求外部CDN。
const assets = import.meta.glob([
  '../../node_modules/pdfjs-dist/cmaps/*.bcmap',
  '../../node_modules/pdfjs-dist/standard_fonts/*.{pfb,ttf}',
], { eager: true, query: '?url&no-inline', import: 'default' }) as Record<string, string>
class LocalBinaryDataFactory {
  async fetch({ kind, filename }: { kind: string; filename: string }) {
    const folder = kind === 'cMapUrl' ? 'cmaps' : kind === 'standardFontDataUrl' ? 'standard_fonts' : ''
    const url = assets[`../../node_modules/pdfjs-dist/${folder}/${filename}`]
    if (!url) throw new Error('缺少PDF字体资源')
    const response = await window.fetch(url)
    if (!response.ok) throw new Error('PDF字体资源加载失败')
    return new Uint8Array(await response.arrayBuffer())
  }
}

export default function PdfPreview({ blob }: { blob: Blob }) {
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null)
  const [page, setPage] = useState(1)
  const [width, setWidth] = useState(500)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  const [rendered, setRendered] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const canvas = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    let active = true, loading: PDFDocumentLoadingTask | undefined
    setDoc(null); setPage(1); setError(''); setBusy(true); setRendered(false)
    Promise.all([import('pdfjs-dist'), blob.arrayBuffer()]).then(([pdfjs, data]) => {
      if (!active) return
      pdfjs.GlobalWorkerOptions.workerSrc = workerUrl
      loading = pdfjs.getDocument({ data: new Uint8Array(data), BinaryDataFactory: LocalBinaryDataFactory,
        useWorkerFetch: false, useWasm: false })
      return loading.promise.then(result => { if (active) setDoc(result) })
    }).catch(() => { if (active) { setError('PDF预览失败，请下载文件查看'); setBusy(false) } })
    return () => { active = false; loading?.destroy() }
  }, [blob])

  useEffect(() => {
    if (!box.current) return
    const observer = new ResizeObserver(() => { if (box.current) setWidth(Math.max(200, box.current.clientWidth - 2)) })
    observer.observe(box.current)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    if (!doc || !canvas.current) return
    let active = true, task: RenderTask | undefined
    setBusy(true); setRendered(false)
    doc.getPage(page).then(pdfPage => {
      if (!active) return
      const scale = Math.min(width / pdfPage.getViewport({ scale: 1 }).width, 1.6)
      const viewport = pdfPage.getViewport({ scale })
      const ratio = Math.min(window.devicePixelRatio || 1, 2)
      const target = canvas.current!
      target.width = Math.ceil(viewport.width * ratio); target.height = Math.ceil(viewport.height * ratio)
      target.style.width = `${viewport.width}px`; target.style.height = `${viewport.height}px`
      task = pdfPage.render({ canvas: target, viewport, transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0] })
      return task.promise.then(() => { if (active) { setRendered(true); setBusy(false) } })
    }).catch(e => {
      if (active && e.name !== 'RenderingCancelledException') { setError('PDF页面显示失败，请下载文件查看'); setBusy(false) }
    })
    return () => { active = false; task?.cancel() }
  }, [doc, page, width])

  return <div ref={box} data-testid="pdf-preview">
    <Space wrap style={{ marginBottom: 12 }}>
      <Button disabled={!doc || page <= 1 || busy} onClick={() => setPage(page - 1)}>上一页</Button>
      <span aria-live="polite">{doc ? `第 ${page} / ${doc.numPages} 页` : '正在读取PDF'}</span>
      <Button disabled={!doc || page >= doc.numPages || busy} onClick={() => setPage(page + 1)}>下一页</Button>
    </Space>
    {error && <Alert type="error" message={error} />}
    <Spin spinning={busy}>
      <div style={{ maxHeight: '65vh', overflow: 'auto', textAlign: 'center', background: '#eee', padding: 0 }}>
        <canvas ref={canvas} role="img" aria-label={`族谱PDF第${page}页`} data-rendered={rendered}
          style={{ display: 'block', margin: '0 auto', background: '#fff', maxWidth: '100%' }} />
      </div>
    </Spin>
  </div>
}
