# العربية

وجود DOI حقيقي في المرجع لا يعني أن العنوان والسنة يطابقانه.

بنيت CiteReceipt: أداة Python تجلب بيانات Crossref الحية، وتقارن عنوان المرجع وسنته وتكشف DOI المكرر. تنتج تقرير HTML أو JSON مؤرخًا، بدون مفتاح API أو مكتبات خارجية للتشغيل.

اجتازت 19 اختبارًا، ونجحت التجربة المتصلة في كشف مرجع تجريبي مكرر بعنوان وسنة مختلفين أُدخلا عمدًا. المطابقة تخص بيانات المرجع؛ لا تثبت صحة الدراسة ولا تتحقق من سحبها.

الكود والصور والتجربة الفعلية:
https://github.com/dxrkf/citereceipt

#Python #OpenSource #Research #Productivity

# English

A real DOI can still be paired with the wrong title or year.

CiteReceipt compares a JSON bibliography with live Crossref metadata, flags duplicate DOIs and creates a timestamped HTML or JSON receipt. Python standard library only; no API key.

Includes 19 deterministic tests and a connected demonstration that catches a deliberately duplicated reference with an incorrect title and year. It checks metadata, not scientific quality or retraction status.

https://github.com/dxrkf/citereceipt

#Python #OpenSource #Crossref #ResearchTools

## Assets

- `assets/cover.png`: project overview diagram.
- `assets/live-result.png`: exact data visualization rendered from `examples/live-receipt.json`, not a fabricated app screenshot.
