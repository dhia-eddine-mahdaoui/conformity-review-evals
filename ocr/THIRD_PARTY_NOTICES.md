# English OCR model

The bundled `eng.traineddata.gz` is the English `4.0.0_best_int` model from
[`@tesseract.js-data/eng@1.0.0`](https://cdn.jsdelivr.net/npm/@tesseract.js-data/eng@1.0.0/4.0.0_best_int/eng.traineddata.gz).
It is byte-for-byte identical to that artifact. Its SHA-256 is
`45b4cb346724ac1774f1c36f42f182b887bcdb28ebe63e6fff90ac41f3fcff91`.

The [Tesseract OCR project](https://github.com/tesseract-ocr/tessdata_best)
provides the original Tessdata Best model under Apache License 2.0.
The [Tesseract.js language data project](https://github.com/naptha/tessdata/tree/gh-pages)
integerizes and compresses that model and provides the same license in its
[source repository](https://github.com/naptha/tessdata/blob/gh-pages/LICENSE).
This repository includes the [Apache License 2.0 text](LICENSE-APACHE-2.0.txt)
for the bundled model. The npm package manifest lists MIT. The files shared
here include only the trained model from that package.
