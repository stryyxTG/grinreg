from __future__ import annotations

import aiohttp
import asyncio
import logging
import time

logger = logging.getLogger(__name__)


class CaptchaSolver:
    def __init__(self, api_key: str, service: str = "rucaptcha"):
        self.api_key = api_key
        self.service = service
        self.create_task_url = "https://api.rucaptcha.com/createTask"
        self.get_result_url = "https://api.rucaptcha.com/getTaskResult"

    async def solve_recaptcha_v2(
        self,
        sitekey: str,
        page_url: str = "https://web.telegram.org",
        timeout: int = 240,
    ) -> str:
        """
        Решает reCAPTCHA v2 через RuCaptcha с автоматическим перебором методов
        """
        async with aiohttp.ClientSession() as session:
            # Пробуем разные методы
            methods = [
                self._solve_with_method(session, sitekey, page_url, "RecaptchaV2TaskProxyless", timeout),
                self._solve_with_method(session, sitekey, page_url, "RecaptchaV2Task", timeout),
            ]

            for method_coro in methods:
                try:
                    return await method_coro
                except Exception as e:
                    logger.warning(f"Метод не сработал: {e}, пробуем следующий...")
                    await asyncio.sleep(5)

            raise Exception("Не удалось решить капчу ни одним методом")

    async def _solve_with_method(
        self,
        session: aiohttp.ClientSession,
        sitekey: str,
        page_url: str,
        task_type: str,
        timeout: int,
    ) -> str:
        """Решение капчи с определённым типом задачи"""
        # Для RecaptchaV2Task нужны прокси. Если их нет — пробуем с фейковыми
        task_data = {
            "type": task_type,
            "websiteURL": page_url,
            "websiteKey": sitekey,
            "isInvisible": False,
        }

        # Если это задача с прокси — добавляем заглушку
        if task_type == "RecaptchaV2Task":
            # Используем публичный прокси (можно заменить на свой)
            proxy = {
                "type": "http",
                "proxyAddress": "45.77.144.123",  # публичный прокси
                "proxyPort": 80,
            }
            task_data.update(proxy)
            logger.info("Использую RecaptchaV2Task с публичным прокси")

        task_payload = {
            "clientKey": self.api_key,
            "task": task_data,
            "softId": 3898,
        }

        logger.info(f"Отправка капчи с методом {task_type}: sitekey={sitekey[:20]}..., pageurl={page_url}")

        async with session.post(self.create_task_url, json=task_payload) as resp:
            result = await resp.json()
            logger.info(f"Ответ createTask ({task_type}): {result}")

            if result.get("errorId", 0) != 0:
                error_desc = result.get("errorDescription", "Unknown error")
                if "WORKERS_UNAVAILABLE" in error_desc or "ERROR_ZERO_BALANCE" in error_desc:
                    raise Exception(f"Ошибка RuCaptcha: {error_desc}")
                raise Exception(f"Ошибка RuCaptcha: {error_desc}")

            task_id = result.get("taskId")
            if not task_id:
                raise Exception("RuCaptcha не вернул taskId")

            logger.info(f"Задача создана, taskId: {task_id} ({task_type})")

        start_time = time.time()
        attempts = 0

        while time.time() - start_time < timeout:
            await asyncio.sleep(3)
            attempts += 1

            result_payload = {
                "clientKey": self.api_key,
                "taskId": task_id,
            }

            async with session.post(self.get_result_url, json=result_payload) as resp:
                result = await resp.json()
                logger.debug(f"Попытка {attempts} ({task_type}): {result}")

                if result.get("errorId", 0) != 0:
                    error_desc = result.get("errorDescription", "Unknown error")
                    raise Exception(f"Ошибка RuCaptcha: {error_desc}")

                status = result.get("status")
                if status == "ready":
                    solution = result.get("solution", {})
                    token = solution.get("gRecaptchaResponse") or solution.get("token")
                    if token:
                        logger.info(f"✅ Капча решена ({task_type})! Токен: {token[:30]}...")
                        return token
                    else:
                        raise Exception("RuCaptcha вернул решение без токена")

                elif status == "processing":
                    continue
                else:
                    raise Exception(f"Неизвестный статус: {status}")

        raise TimeoutError(f"Время ожидания решения капчи истекло ({timeout}с)")