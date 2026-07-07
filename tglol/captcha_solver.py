from __future__ import annotations

import logging
import asyncio
from python_rucaptcha import ReCaptchaV2

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
        """
        Решает reCAPTCHA v2 через официальную библиотеку python-rucaptcha.
        """
        try:
            # Создаем задачу через официальную библиотеку
            solver = ReCaptchaV2.ReCaptchaV2(
                rucaptcha_key=self.api_key,
                site_key=sitekey,
                page_url=page_url,
                # Дополнительные параметры для сложных капч
                invisible=False,
                soft_id=3898,
            )

            # Запускаем решение (синхронный метод, но запускаем в executor)
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                solver.captcha_handler,
            )

            logger.info(f"Ответ от python-rucaptcha: {result}")

            if result.get("errorId", 0) != 0:
                error_desc = result.get("errorDescription", "Unknown error")
                raise Exception(f"Ошибка RuCaptcha: {error_desc}")

            if result.get("status") == "ready":
                token = result.get("solution", {}).get("gRecaptchaResponse")
                if token:
                    logger.info(f"✅ Капча решена!")
                    return token
                else:
                    raise Exception("Нет токена в ответе")

            raise Exception(f"Неизвестный статус: {result.get('status')}")

        except Exception as e:
            logger.error(f"Ошибка при решении капчи: {e}")
            raise