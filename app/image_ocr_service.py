from __future__ import annotations

import asyncio
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

from PIL import Image, ImageOps

from app.config import (
    IMAGE_OCR_DEBUG_SAVE,
    IMAGE_OCR_LANGS,
    IMAGE_OCR_MAX_BYTES,
    IMAGE_OCR_MAX_SIDE,
    IMAGE_OCR_PSMS,
    IMAGE_OCR_TESSERACT_CMD,
    IMAGE_OCR_USE_OPENCV,
    OCR_DEBUG_DIR,
    OCR_TEMP_DIR,
)


class ImageOcrUnavailable(RuntimeError):
    pass


class ImageOcrError(RuntimeError):
    pass


@dataclass
class OcrAttempt:
    candidate: str
    psm: int
    text: str
    chars: int
    tokens: int
    confidence: float
    score: float


def is_parse_image_command(text: str) -> bool:
    return re.sub(r"\s+", "", str(text or "")) == "解析"


def _download_temp_image(image_url: str) -> Path:
    request = Request(
        image_url,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    OCR_TEMP_DIR.mkdir(parents=True, exist_ok=True)
    temp_path = OCR_TEMP_DIR / f"{uuid.uuid4().hex}.img"

    downloaded = 0
    try:
        with urlopen(request, timeout=30) as response:
            content_type = response.headers.get("Content-Type", "")
            if content_type and not content_type.lower().startswith("image/"):
                raise ImageOcrError("replied message is not an image")

            with temp_path.open("wb") as file:
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break

                    downloaded += len(chunk)
                    if downloaded > IMAGE_OCR_MAX_BYTES:
                        raise ImageOcrError("image is too large")

                    file.write(chunk)

        return temp_path
    except Exception:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise


def _open_image(path: Path) -> Image.Image:
    image = Image.open(path)
    image = ImageOps.exif_transpose(image)
    return image.convert("RGB")


def _resize_for_ocr(
    image: Image.Image,
    target_side: int = IMAGE_OCR_MAX_SIDE,
) -> Image.Image:
    max_side = max(image.size)
    if max_side <= 0:
        return image

    if max_side < target_side:
        scale = target_side / max_side
    elif max_side > target_side * 1.5:
        scale = target_side / max_side
    else:
        return image

    return image.resize(
        (
            max(1, int(image.width * scale)),
            max(1, int(image.height * scale)),
        ),
        Image.Resampling.LANCZOS,
    )


def _prepare_pillow_image(image: Image.Image) -> Image.Image:
    image = _resize_for_ocr(image.convert("L"), 1400)
    image = ImageOps.autocontrast(image)
    return ImageOps.expand(image, border=24, fill=255)


def _pil_from_cv2_gray(array) -> Image.Image:
    return Image.fromarray(array).convert("L")


def _save_debug_candidate(name: str, image: Image.Image) -> None:
    if not IMAGE_OCR_DEBUG_SAVE:
        return

    OCR_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", name)
    image.save(OCR_DEBUG_DIR / f"{uuid.uuid4().hex}_{safe_name}.png")


def _deskew_if_small_angle(gray):
    try:
        import cv2
        import numpy as np
    except Exception:
        return gray

    try:
        inverted = cv2.bitwise_not(gray)
        coords = np.column_stack(np.where(inverted > 0))
        if len(coords) < 100:
            return gray

        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = 90 + angle

        if abs(angle) < 0.5 or abs(angle) > 12:
            return gray

        height, width = gray.shape[:2]
        center = (width // 2, height // 2)
        matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
        return cv2.warpAffine(
            gray,
            matrix,
            (width, height),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REPLICATE,
        )
    except Exception:
        return gray


def _build_opencv_candidates(image: Image.Image) -> list[tuple[str, Image.Image]]:
    try:
        import cv2
        import numpy as np
    except Exception:
        return []

    try:
        image = _resize_for_ocr(image.convert("RGB"), IMAGE_OCR_MAX_SIDE)
        rgb = np.array(image)
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        gray = _deskew_if_small_angle(gray)

        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        denoised = cv2.fastNlMeansDenoising(enhanced, None, 7, 7, 21)

        sharpen_kernel = np.array(
            [[0, -1, 0], [-1, 5, -1], [0, -1, 0]],
            dtype=np.float32,
        )
        conservative = cv2.filter2D(enhanced, -1, sharpen_kernel)
        conservative = cv2.copyMakeBorder(
            conservative,
            24,
            24,
            24,
            24,
            cv2.BORDER_CONSTANT,
            value=255,
        )

        adaptive = cv2.adaptiveThreshold(
            denoised,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            35,
            11,
        )
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 1))
        adaptive = cv2.morphologyEx(
            adaptive,
            cv2.MORPH_OPEN,
            kernel,
            iterations=1,
        )
        adaptive = cv2.copyMakeBorder(
            adaptive,
            24,
            24,
            24,
            24,
            cv2.BORDER_CONSTANT,
            value=255,
        )

        blurred = cv2.medianBlur(enhanced, 3)
        _, otsu = cv2.threshold(
            blurred,
            0,
            255,
            cv2.THRESH_BINARY + cv2.THRESH_OTSU,
        )
        otsu = cv2.copyMakeBorder(
            otsu,
            24,
            24,
            24,
            24,
            cv2.BORDER_CONSTANT,
            value=255,
        )

        return [
            ("conservative", _pil_from_cv2_gray(conservative)),
            ("adaptive", _pil_from_cv2_gray(adaptive)),
            ("otsu", _pil_from_cv2_gray(otsu)),
        ]
    except Exception:
        return []


def build_ocr_candidates(image: Image.Image) -> list[tuple[str, Image.Image]]:
    base = ("pillow", _prepare_pillow_image(image))
    if not IMAGE_OCR_USE_OPENCV:
        candidates = [base]
    else:
        opencv_candidates = _build_opencv_candidates(image)
        candidates = opencv_candidates or [base]

    if base[0] not in {name for name, _ in candidates}:
        candidates.append(base)

    candidates = candidates[:3]
    for name, candidate in candidates:
        _save_debug_candidate(name, candidate)

    return candidates


def _normalize_ocr_text(text: str) -> str:
    text = str(text or "")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    return text[:6000]


def _valid_chars(text: str) -> list[str]:
    return re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", str(text or ""))


def is_meaningful_ocr_text(text: str) -> bool:
    normalized = re.sub(r"\s+", "", str(text or ""))
    if len(normalized) < 3:
        return False

    meaningful_chars = _valid_chars(normalized)
    if len(meaningful_chars) < 3:
        return False

    return len(meaningful_chars) / max(len(normalized), 1) >= 0.35


def _parse_confidence(value) -> float | None:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None

    if confidence < 0:
        return None
    return confidence


def _extract_attempt(
    candidate_name: str,
    image: Image.Image,
    psm: int,
    lang: str = IMAGE_OCR_LANGS,
) -> OcrAttempt:
    try:
        import pytesseract
        from pytesseract import Output
    except Exception as exc:
        raise ImageOcrUnavailable("pytesseract is not installed") from exc

    data = pytesseract.image_to_data(
        image,
        lang=lang,
        config=f"--oem 1 --psm {psm}",
        output_type=Output.DICT,
        timeout=18,
    )

    tokens: list[str] = []
    confidences: list[float] = []
    for token, confidence_value in zip(
        data.get("text", []),
        data.get("conf", []),
    ):
        token = str(token or "").strip()
        if not token:
            continue

        tokens.append(token)
        confidence = _parse_confidence(confidence_value)
        if confidence is not None:
            confidences.append(confidence)

    text = _normalize_ocr_text(" ".join(tokens))
    chars = len(_valid_chars(text))
    avg_confidence = (
        sum(confidences) / len(confidences)
        if confidences
        else 0.0
    )
    score = chars * 1.0 + len(tokens) * 2.0 + avg_confidence * 0.5

    return OcrAttempt(
        candidate=candidate_name,
        psm=psm,
        text=text,
        chars=chars,
        tokens=len(tokens),
        confidence=avg_confidence,
        score=score,
    )


def extract_text_with_score(
    image: Image.Image,
    lang: str,
    psm: int,
) -> tuple[str, float]:
    attempt = _extract_attempt("manual", image, psm, lang)
    return attempt.text, attempt.score


def _extract_best_text(image: Image.Image) -> str:
    try:
        from pytesseract import TesseractError, TesseractNotFoundError
    except Exception as exc:
        raise ImageOcrUnavailable("pytesseract is not installed") from exc

    attempts: list[OcrAttempt] = []
    candidates = build_ocr_candidates(image)

    for candidate_name, candidate_image in candidates:
        for psm in IMAGE_OCR_PSMS[:2]:
            try:
                attempt = _extract_attempt(candidate_name, candidate_image, psm)
            except TesseractNotFoundError as exc:
                raise ImageOcrUnavailable("tesseract executable is not installed") from exc
            except RuntimeError as exc:
                if "timeout" in str(exc).lower():
                    print(f"[OCR] candidate={candidate_name} psm={psm} timeout")
                continue
            except TesseractError:
                continue

            print(
                "[OCR] "
                f"candidate={attempt.candidate} "
                f"psm={attempt.psm} "
                f"chars={attempt.chars} "
                f"confidence={attempt.confidence:.1f} "
                f"score={attempt.score:.1f}"
            )
            attempts.append(attempt)

    if not attempts:
        return ""

    best = max(
        attempts,
        key=lambda item: (
            item.score,
            item.chars,
            item.tokens,
            len(item.text),
        ),
    )
    print(
        "[OCR] "
        f"selected={best.candidate} "
        f"psm={best.psm} "
        f"chars={best.chars}"
    )
    return best.text


def _extract_text_sync(image_url: str) -> str:
    try:
        import pytesseract
        from pytesseract import TesseractNotFoundError
    except Exception as exc:
        raise ImageOcrUnavailable("pytesseract is not installed") from exc

    pytesseract.pytesseract.tesseract_cmd = IMAGE_OCR_TESSERACT_CMD

    path = _download_temp_image(image_url)
    try:
        image = _open_image(path)
        try:
            return _extract_best_text(image)
        except TesseractNotFoundError as exc:
            raise ImageOcrUnavailable("tesseract executable is not installed") from exc
    finally:
        path.unlink(missing_ok=True)


async def extract_image_text(image_url: str) -> str:
    try:
        return await asyncio.to_thread(_extract_text_sync, image_url)
    except ImageOcrUnavailable:
        raise
    except Exception as exc:
        raise ImageOcrError("image OCR failed") from exc


def build_image_parse_prompt(ocr_text: str) -> str:
    return f"""
下面是从用户回复的图片中 OCR 提取出的文字内容。请基于这些文字进行解析，并在需要最新公开信息、资料出处、当前政策规则、产品版本或事实核验时结合联网检索资料回答。

要求：
1. 如果内容是一道题，先给出本题答案，再给出详解。
2. 不要使用 LaTeX，数学表达式用普通文本写清楚。
3. 如果题目或材料信息不足，说明缺少什么条件。
4. 如果经思考和联网搜索资料仍无法解释，说明解析失败的具体原因。
5. 如果不是题目，就按正常带联网搜索能力的 AI 对话方式回答。

图片 OCR 内容：
{ocr_text}
""".strip()
