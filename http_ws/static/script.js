// Инициализация Telegram WebApp (запуск полной версии)
if (window.Telegram && Telegram.WebApp) {
  Telegram.WebApp.ready();
  // Получаем данные пользователя (пример использования API)
  const userId = Telegram.WebApp.initDataUnsafe.user.id;
  console.log("User ID:", userId);
}

// Элементы управления панелями
const filterBtn = document.getElementById('filterBtn');
const filterPanel = document.getElementById('filterPanel');
const closeFilter = document.getElementById('closeFilter');

const rentBtns = document.querySelectorAll('.rentBtn');
const rentPanel = document.getElementById('rentPanel');
const rentInfo = document.getElementById('rentInfo');
const closeRent = document.getElementById('closeRent');

const scanBtn = document.getElementById('scanBtn');
const scanPanel = document.getElementById('scanPanel');
const video = document.getElementById('video');
const canvas = document.getElementById('canvas');
const scanResult = document.getElementById('scanResult');
const stopScan = document.getElementById('stopScan');

let scanning = false;
let stream = null;

// Функции показа/скрытия панелей
filterBtn.onclick = () => { filterPanel.style.display = 'block'; };
closeFilter.onclick = () => { filterPanel.style.display = 'none'; };

rentBtns.forEach(btn => {
  btn.onclick = () => {
    const title = btn.parentElement.querySelector('h3').innerText;
    rentInfo.innerText = `Вы выбрали: ${title}`;
    rentPanel.style.display = 'block';
  };
});
closeRent.onclick = () => { rentPanel.style.display = 'none'; };

scanBtn.onclick = async () => {
  scanPanel.style.display = 'block';
  startScanning();
};
stopScan.onclick = () => {
  stopScanning();
  scanPanel.style.display = 'none';
};

// Запуск сканирования QR через камеру
async function startScanning() {
  if (scanning) return;
  scanning = true;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
    video.srcObject = stream;
    video.setAttribute("playsinline", true); // для iOS
    video.play();
    requestAnimationFrame(tick);
  } catch (err) {
    console.error("Ошибка доступа к камере:", err);
  }
}

// Остановка сканирования
function stopScanning() {
  scanning = false;
  if (stream) {
    stream.getTracks().forEach(track => track.stop());
  }
}

async function sendCanvasFrameStream(diskName, filename, messageId, canvas) {
  const proto = (location.protocol === "https:") ? "wss" : "ws";
  const url = `${proto}://${location.host}/ws/upload`;
  const ws = new WebSocket(url);
  ws.binaryType = "arraybuffer";

  return new Promise((resolve, reject) => {
    ws.onopen = async () => {
      // метаданные
      const meta = {
        type: "meta",
        disk_name: diskName,
        filename: filename || "frame.jpg",
        message_id: messageId || "0",
        user_id: (window.Telegram && Telegram.WebApp && Telegram.WebApp.initDataUnsafe.user) ? Telegram.WebApp.initDataUnsafe.user.id : ""
      };
      ws.send(JSON.stringify(meta));

      // Получаем blob из canvas и стримим чанками
      // разбиваем blob на куски
      canvas.toBlob(async (blob) => {
        const CHUNK_SIZE = 64 * 1024; // 64KB
        let offset = 0;
        while (offset < blob.size) {
          const slice = blob.slice(offset, offset + CHUNK_SIZE);
          const arrayBuffer = await slice.arrayBuffer();
          ws.send(arrayBuffer);
          offset += CHUNK_SIZE;
        }
        // отправляем сообщение об окончании
        ws.send(JSON.stringify({type: "end"}));
      }, "image/jpeg", 0.8);
    };

    ws.onmessage = (ev) => {
      // получаем JSON от сервера
      try {
        const data = JSON.parse(ev.data);
        if (data.type === "result") {
          resolve(data.data);
          ws.close();
        } else if (data.type === "error") {
          reject(new Error(data.message));
          ws.close();
        } else {
          console.log("ws msg", data);
        }
      } catch (e) {
        console.warn("non-json ws message", ev.data);
      }
    };

    ws.onerror = (e) => {
      reject(e);
    };
    ws.onclose = () => {
      // если закрыли без ответа
    };
  });
}


// ----------------- ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ: стрим через WebSocket -----------------
async function sendCanvasFrameStream(diskName, filename, messageId, canvas) {
  const proto = (location.protocol === "https:") ? "wss" : "ws";
  // Используем относительный путь; nginx должен проксировать /ws/upload на host контейнер
  const url = `${proto}://${location.host}/ws/upload`;
  const ws = new WebSocket(url);
  ws.binaryType = "arraybuffer";

  return new Promise((resolve, reject) => {
    let resolved = false;

    const cleanup = () => {
      try { ws.close(); } catch (e) {}
    };

    const onError = (err) => {
      if (!resolved) {
        resolved = true;
        cleanup();
        reject(err);
      }
    };

    ws.onerror = (e) => onError(new Error("WebSocket error"));

    ws.onopen = async () => {
      // Отправляем метаданные первыми (JSON)
      const user = (window.Telegram && Telegram.WebApp && Telegram.WebApp.initDataUnsafe && Telegram.WebApp.initDataUnsafe.user) ? Telegram.WebApp.initDataUnsafe.user : null;
      const meta = {
        type: "meta",
        disk_name: diskName || "",
        filename: filename || `frame_${Date.now()}.jpg`,
        message_id: messageId || `${Date.now()}`,
        user_id: user ? String(user.id) : ""
      };
      ws.send(JSON.stringify(meta));

      // Получаем blob из canvas и стримим чанками (ArrayBuffer)
      canvas.toBlob(async (blob) => {
        try {
          const CHUNK_SIZE = 64 * 1024; // 64KB
          let offset = 0;
          while (offset < blob.size) {
            const slice = blob.slice(offset, offset + CHUNK_SIZE);
            const arrayBuffer = await slice.arrayBuffer();
            // отправляем бинарный фрейм
            ws.send(arrayBuffer);
            offset += CHUNK_SIZE;
            // не ставим задержку — быстрое отправление
          }
          // сигнализируем об окончании передачи
          ws.send(JSON.stringify({ type: "end" }));
        } catch (err) {
          onError(err);
        }
      }, "image/jpeg", 0.85);
    };

    ws.onmessage = (ev) => {
      // Ожидаем JSON-ответ от сервера вида { type: "result", data: {...} }
      try {
        const data = JSON.parse(ev.data);
        if (data.type === "result") {
          if (!resolved) {
            resolved = true;
            cleanup();
            resolve(data.data);
          }
        } else if (data.type === "error") {
          onError(new Error(data.message || "Server error"));
        } else {
          // игнорируем другие служебные сообщения
          console.log("WS info:", data);
        }
      } catch (e) {
        // если сервер присылает бинарные данные — можно их обработать здесь
        console.warn("Non-JSON ws message:", ev.data);
      }
    };

    ws.onclose = (ev) => {
      if (!resolved) {
        resolved = true;
        reject(new Error("WebSocket closed without result"));
      }
    };

    // Таймаут на всю передачу + обработку
    const TIMEOUT_MS = 30000; // 30s
    const to = setTimeout(() => {
      if (!resolved) {
        resolved = true;
        try { ws.close(); } catch (e) {}
        reject(new Error("Upload timeout"));
      }
    }, TIMEOUT_MS);
    // очищаем таймаут при завершении
    const origResolve = resolve;
    resolve = (val) => { clearTimeout(to); origResolve(val); };
    const origReject = reject;
    reject = (err) => { clearTimeout(to); origReject(err); };
  });
}

// ----------------- ИНТЕГРАЦИЯ В tick() -----------------
async function handleFoundQRCode(codeData) {
  // UI: показываем временный текст; потом будет обновлён по ответу сервера
  scanResult.innerText = "QR-код: " + codeData + " — отправка на сервер...";
  // Подобираем диск, filename и messageId (пример — берём выбранный диск или placeholder)
  const selectedDiskName = window.selectedDiskName || "unknown_disk";
  const filename = `${selectedDiskName.replace(/\s+/g,'_')}_${Date.now()}.jpg`;
  const messageId = `${Date.now()}`;

  try {
    // отправляем canvas (глобальная canvas) как стрим через WebSocket->gRPC
    const result = await sendCanvasFrameStream(selectedDiskName, filename, messageId, canvas);

    // Ожидаем, что result содержит данные подтверждения от сервера,
    // например { received_chunks: N, saved_paths: [...], nickname: "...", username: "...", datetime: "...", disk: "..." }
    console.log("Upload result:", result);

    // Обновляем UI в соответствии с твоим требованием:
    // - панель становится с зелёным оттенком
    // - показываем белую галку
    // - отображаем данные (nickname, username, datetime, disk)
    scanPanel.style.background = "linear-gradient(180deg, #e6ffed 0%, #b7f0c9 100%)";
    scanPanel.style.color = "#0b3d1a";
    // убираем видео, показываем подтверждение
    video.style.display = "none";
    canvas.style.display = "none";
    // создаём блок подтверждения
    const okBlock = document.createElement("div");
    okBlock.id = "confirmBlock";
    okBlock.style.display = "flex";
    okBlock.style.flexDirection = "column";
    okBlock.style.alignItems = "center";
    okBlock.style.justifyContent = "center";
    okBlock.style.padding = "20px";

    const check = document.createElement("div");
    check.innerText = "✔";
    check.style.fontSize = "64px";
    check.style.color = "#fff";
    check.style.background = "#2ecc71";
    check.style.borderRadius = "999px";
    check.style.width = "96px";
    check.style.height = "96px";
    check.style.display = "flex";
    check.style.alignItems = "center";
    check.style.justifyContent = "center";
    check.style.marginBottom = "12px";

    const details = document.createElement("pre");
    details.style.whiteSpace = "pre-wrap";
    details.style.textAlign = "center";
    details.style.background = "transparent";
    details.style.border = "none";
    details.style.fontSize = "14px";

    // Формируем текст с тем, что вернёт сервер. Подстраховываемся на случай разных форматов.
    const nickname = result.nickname || result.nick || result.user_nick || "";
    const username = result.username || (window.Telegram && Telegram.WebApp && Telegram.WebApp.initDataUnsafe && Telegram.WebApp.initDataUnsafe.user ? Telegram.WebApp.initDataUnsafe.user.username : "") || "";
    const datetime = result.datetime || result.time || result.date || "";
    const disk = result.disk || selectedDiskName || "";

    details.innerText = `Ник: ${nickname}\nUsername: ${username}\nДиск: ${disk}\nДата/время: ${datetime}`;

    okBlock.appendChild(check);
    okBlock.appendChild(details);

    // чистим старый результат, вставляем подтверждение
    scanPanel.appendChild(okBlock);

    // После успешного подтверждения можно показать кнопку "получить диски" над витриной.
    // Здесь вызываем функцию, которая активирует кнопку в основном UI (предположим, showPickupButton())
    if (typeof showPickupButton === "function") {
      showPickupButton();
    }

  } catch (err) {
    console.error("Upload failed:", err);
    scanResult.innerText = "Ошибка отправки: " + (err.message || err);
    // при ошибке можно возобновить сканирование или предложить повтор
    setTimeout(() => {
      // очистка ошибок, вернуть видео
      scanResult.innerText = "";
      video.style.display = "";
      canvas.style.display = "none";
      startScanning(); // перезапускаем сканирование
    }, 1500);
  }
}

// Сам tick() — используем асинхронную обработку при нахождении QR
function tick() {
  if (!scanning) return;
  if (video.readyState === video.HAVE_ENOUGH_DATA) {
    canvas.hidden = false;
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
    const code = jsQR(imageData.data, imageData.width, imageData.height);
    if (code) {
      // найден QR — останавливаем сканирование и обрабатываем
      stopScanning(); // остановит requestAnimationFrame цикл
      // Выводим информацию и запускаем асинхронную отправку
      scanResult.innerText = "QR-код: " + code.data + " — обрабатываем...";
      // запускаем обработчик, не блокируя основной поток
      handleFoundQRCode(code.data);
      return;
    }
  }
  requestAnimationFrame(tick);
}
