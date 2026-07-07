from __future__ import annotations

import logging
import asyncio

# Правильный импорт для новой версии
from python_rucaptcha import ReCaptchaV2 as RecaptchaV2

logger = logging.getLogger(__name__)


class CaptchaSolver:
    def __init__(self, api_key: str, service: str = "rucaptcha"):
        self.api_key = api_key
        self.service = service

    async def solve_recaptcha_v2(
        self,
        sitekey: str,
        page_url: str = "https://web.telegram.org",
        timeout: int = 180,
    ) -> str:
        try:
            # Создаем задачу
            solver = RecaptchaV2.ReCaptchaV2(
                rucaptcha_key=self.api_key,
                site_key=sitekey,
                page_url=page_url,
                invisible=False,
                soft_id=3898,
            )

            # Решаем капчу (синхронный метод)
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                solver.captcha_handler,
            )

            logger.info(f"Ответ: {result}")

            if result.get("errorId", 0) != 0:
                raise Exception(f"Ошибка RuCaptcha: {result.get('errorDescription', 'Unknown error')}")

            token = result.get("solution", {}).get("gRecaptchaResponse")
            if token:
                logger.info(f"✅ Капча решена!")
                return token

            raise Exception("Нет токена в ответе")

        except Exception as e:
            logger.error(f"Ошибка при решении капчи: {e}")
            raise