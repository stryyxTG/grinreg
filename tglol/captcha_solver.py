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
        timeout: int = 180,
    ) -> str:
        async with aiohttp.ClientSession() as session:
            # 1. Создаем задачу
            task_payload = {
                "clientKey": self.api_key,
                "task": {
                    "type": "RecaptchaV2TaskProxyless",
                    "websiteURL": page_url,
                    "websiteKey": sitekey,
                    "isInvisible": False,
                },
                "softId": 3898,
            }

            logger.info(f"Отправка капчи в RuCaptcha: sitekey={sitekey[:20]}..., pageurl={page_url}")

            async with session.post(self.create_task_url, json=task_payload) as resp:
                result = await resp.json()
                logger.info(f"Ответ createTask: {result}")

                if result.get("errorId", 0) != 0:
                    error_desc = result.get("errorDescription", "Unknown error")
                    raise Exception(f"Ошибка RuCaptcha: {error_desc}")

                task_id = result.get("taskId")
                if not task_id:
                    raise Exception("RuCaptcha не вернул taskId")

                logger.info(f"Задача создана, taskId: {task_id}")

            # 2. Ожидаем результат
            start_time = time.time()
            attempts = 0

            while time.time() - start_time < timeout:
                await asyncio.sleep(2)
                attempts += 1

                result_payload = {
                    "clientKey": self.api_key,
                    "taskId": task_id,
                }

                async with session.post(self.get_result_url, json=result_payload) as resp:
                    result = await resp.json()
                    logger.debug(f"Попытка {attempts}: {result}")

                    if result.get("errorId", 0) != 0:
                        error_desc = result.get("errorDescription", "Unknown error")
                        raise Exception(f"Ошибка RuCaptcha: {error_desc}")

                    status = result.get("status")
                    if status == "ready":
                        solution = result.get("solution", {})
                        token = solution.get("gRecaptchaResponse") or solution.get("token")
                        if token:
                            logger.info(f"✅ Капча решена! Токен: {token[:30]}...")
                            return token
                        else:
                            raise Exception("RuCaptcha вернул решение без токена")

                    elif status == "processing":
                        if attempts % 5 == 0:
                            logger.info(f"Ожидаем... попытка {attempts}")
                        continue
                    else:
                        raise Exception(f"Неизвестный статус: {status}")

            raise TimeoutError(f"Время ожидания решения капчи истекло ({timeout}с)")