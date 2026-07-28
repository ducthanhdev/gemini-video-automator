let uploadedFiles = [];
let lastStatusResponse = null;
let latestQueueList = [];

document.addEventListener("DOMContentLoaded", () => {
    initQRCode();
    initSettings();
    initUploadDropzone();
    initProductUrlParser();
    initActionButtons();
    initTaskCreation();
    initLayoutResizer();
    initVideoModal();
    
    startPolling();
    loadVideos();
});

function initQRCode() {
    const urlTextElement = document.querySelector(".url-text");
    if (!urlTextElement) return;
    
    const localUrl = urlTextElement.innerText.trim();
    const qrContainer = document.getElementById("qrcode");
    
    if (qrContainer && typeof QRCode !== "undefined") {
        new QRCode(qrContainer, {
            text: localUrl,
            width: 128,
            height: 128,
            colorDark: "#000000",
            colorLight: "#ffffff",
            correctLevel: QRCode.CorrectLevel.M
        });
    }
}

// 2. TẢI CẤU HÌNH BAN ĐẦU
async function initSettings() {
    try {
        const res = await fetch("/api/settings");
        if (res.ok) {
            const data = await res.json();
            document.getElementById("api-key").value = data.api_key || "";
            document.getElementById("prompt-mode").value = data.prompt_mode || "api";
            document.getElementById("long-video-mode").value = data.long_video_mode || "last_frame";
            document.getElementById("system-instruction").value = data.system_instruction || "";
            document.getElementById("meta-prompt-template").value = data.meta_prompt_template || "";
        }
    } catch (e) {
        console.error("Lỗi nạp cấu hình cài đặt:", e);
    }

    // Hiệu ứng đóng/mở cấu hình nâng cao
    const advancedToggle = document.getElementById("advanced-toggle");
    const advancedContent = document.getElementById("advanced-content");
    if (advancedToggle && advancedContent) {
        advancedToggle.addEventListener("click", () => {
            advancedToggle.classList.toggle("active");
            advancedContent.classList.toggle("show");
        });
    }

    // Lắng nghe sự kiện lưu cấu hình
    document.getElementById("btn-save-settings").addEventListener("click", async () => {
        const apiKey = document.getElementById("api-key").value;
        const promptMode = document.getElementById("prompt-mode").value;
        const longVideoMode = document.getElementById("long-video-mode").value;
        const systemInstruction = document.getElementById("system-instruction").value;
        const metaPromptTemplate = document.getElementById("meta-prompt-template").value;

        try {
            const res = await fetch("/api/settings", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    api_key: apiKey,
                    prompt_mode: promptMode,
                    long_video_mode: longVideoMode,
                    system_instruction: systemInstruction,
                    meta_prompt_template: metaPromptTemplate
                })
            });
            if (res.ok) {
                showToast("Đã lưu cấu hình thành công!");
            } else {
                showToast("Lỗi khi lưu cấu hình.", true);
            }
        } catch (e) {
            showToast("Lỗi kết nối máy chủ.", true);
        }
    });
}

// 3. XỬ LÝ KÉO THẢ & UPLOAD ẢNH
function initUploadDropzone() {
    const dropzone = document.getElementById("dropzone");
    const fileInput = document.getElementById("image-upload");
    const previewGallery = document.getElementById("preview-gallery");
    const btnCreate = document.getElementById("btn-create-task");

    // Click vào dropzone kích hoạt chọn file ẩn
    dropzone.addEventListener("click", () => fileInput.click());

    dropzone.addEventListener("dragover", (e) => {
        e.preventDefault();
        dropzone.classList.add("dragover");
    });

    dropzone.addEventListener("dragleave", () => {
        dropzone.classList.remove("dragover");
    });

    dropzone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropzone.classList.remove("dragover");
        if (e.dataTransfer.files.length > 0) {
            handleFiles(e.dataTransfer.files);
        }
    });

    fileInput.addEventListener("change", (e) => {
        if (e.target.files.length > 0) {
            handleFiles(e.target.files);
        }
    });

    async function handleFiles(files) {
        const formData = new FormData();
        let hasImage = false;
        
        for (let i = 0; i < files.length; i++) {
            if (files[i].type.startsWith("image/")) {
                formData.append("files", files[i]);
                hasImage = true;
            }
        }
        
        if (!hasImage) {
            showToast("Vui lòng chỉ chọn các tệp hình ảnh.", true);
            return;
        }

        showToast("Đang tải ảnh lên máy chủ...");

        try {
            const res = await fetch("/api/upload", {
                method: "POST",
                body: formData
            });
            
            if (res.ok) {
                const data = await res.json();
                // Bổ sung các filename vừa upload vào danh sách
                data.filenames.forEach(filename => {
                    uploadedFiles.push(filename);
                    createPreviewThumbnail(filename);
                });
                validateForm();
                showToast("Tải ảnh lên thành công!");
            } else {
                showToast("Không thể tải ảnh lên.", true);
            }
        } catch (e) {
            showToast("Lỗi kết nối khi tải ảnh.", true);
        }
    }
}

function createPreviewThumbnail(filename) {
    const previewGallery = document.getElementById("preview-gallery");
    if (!previewGallery) return;

    const item = document.createElement("div");
    item.className = "preview-item";
    item.dataset.filename = filename;
    
    item.innerHTML = `
        <img src="/uploads/${filename}" style="width:100%;height:100%;object-fit:cover;border-radius:8px;" onerror="this.onerror=null;this.parentNode.innerHTML='<div style=\'width:100%;height:100%;background:rgba(255,255,255,0.05);display:flex;align-items:center;justify-content:center;font-size:20px;\'>🖼️</div><div class=\'remove-btn\'>✕</div>'">
        <div class="remove-btn">✕</div>
    `;
    
    item.querySelector(".remove-btn").addEventListener("click", (e) => {
        e.stopPropagation();
        uploadedFiles = uploadedFiles.filter(f => f !== filename);
        item.remove();
        validateForm();
    });
    
    previewGallery.appendChild(item);
}

// 3.5 BÓC TÁCH THÔNG TIN TỪ LINK SẢN PHẨM
function initProductUrlParser() {
    const btnParse = document.getElementById("btn-parse-url");
    const urlInput = document.getElementById("product-url-input");
    const statusText = document.getElementById("parse-url-status");
    const descInput = document.getElementById("user-description");

    if (!btnParse || !urlInput) return;

    btnParse.addEventListener("click", async (e) => {
        if (e) e.preventDefault();
        const url = urlInput.value.trim();
        if (!url) {
            showToast("Vui lòng nhập đường dẫn link sản phẩm.", true);
            return;
        }

        btnParse.disabled = true;
        btnParse.innerHTML = `<span class="icon">⏳</span> Đang bóc tách...`;
        statusText.innerText = "Đang mở link sản phẩm (Tạm dừng 5s để bạn kéo mảnh ghép Captcha trên Chrome nếu có)...";
        statusText.style.color = "var(--text-muted)";

        try {
            const res = await fetch("/api/parse-url", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ url: url })
            });

            const result = await res.json();

            if (res.ok && result.status === "success") {
                const data = result.data;
                if (data.full_text) {
                    descInput.value = data.full_text;
                }
                
                if (data.images && data.images.length > 0) {
                    data.images.forEach(filename => {
                        if (!uploadedFiles.includes(filename)) {
                            uploadedFiles.push(filename);
                            createPreviewThumbnail(filename);
                        }
                    });
                }

                validateForm();
                statusText.innerText = `✅ Đã lấy thành công: ${data.title} (${data.images.length} ảnh sản phẩm)`;
                statusText.style.color = "#4caf50";
                showToast("Đã bóc tách dữ liệu sản phẩm thành công!");
            } else {
                const errorMsg = result.detail || "Không thể lấy thông tin từ đường dẫn này.";
                statusText.innerText = `❌ ${errorMsg}`;
                statusText.style.color = "#f44336";
                showToast(errorMsg, true);
            }
        } catch (e) {
            console.error("Lỗi khi bóc tách link:", e);
            statusText.innerText = "❌ Lỗi kết nối máy chủ.";
            statusText.style.color = "#f44336";
            showToast("Lỗi kết nối máy chủ.", true);
        } finally {
            btnParse.disabled = false;
            btnParse.innerHTML = `<span class="icon">🔗</span> Lấy thông tin`;
        }
    });
}

// 4. KIỂM TRA ĐIỀU KIỆN KÍCH HOẠT NÚT TẠO VIDEO
function validateForm() {
    const desc = document.getElementById("user-description").value.trim();
    const btnCreate = document.getElementById("btn-create-task");
    
    if (uploadedFiles.length > 0 && desc.length > 0) {
        btnCreate.removeAttribute("disabled");
    } else {
        btnCreate.setAttribute("disabled", "true");
    }
}

// 5. TẠO NHIỆM VỤ MỚI
function initTaskCreation() {
    const descInput = document.getElementById("user-description");
    const durationSelect = document.getElementById("video-duration");
    const ratioSelect = document.getElementById("video-ratio");
    const btnCreate = document.getElementById("btn-create-task");

    descInput.addEventListener("input", validateForm);

    btnCreate.addEventListener("click", async () => {
        const desc = descInput.value.trim();
        const duration = parseInt(durationSelect.value);
        const ratio = ratioSelect.value;

        if (uploadedFiles.length === 0 || !desc) return;

        // Vô hiệu hóa nút và đổi chữ để chống bấm đúp/bấm nhiều lần
        btnCreate.setAttribute("disabled", "true");
        const originalText = btnCreate.innerText;
        btnCreate.innerText = "Đang xử lý...";

        try {
            const res = await fetch("/api/tasks", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    images: uploadedFiles,
                    user_description: desc,
                    duration: duration,
                    ratio: ratio
                })
            });

            if (res.ok) {
                showToast("Đã thêm nhiệm vụ vào hàng đợi!");
                // Reset form
                descInput.value = "";
                document.getElementById("preview-gallery").innerHTML = "";
                uploadedFiles = [];
                validateForm();
                
                // Refresh danh sách nhiệm vụ lập tức
                pollStatus();
            } else {
                showToast("Lỗi khi thêm nhiệm vụ.", true);
                btnCreate.removeAttribute("disabled");
            }
        } catch (e) {
            showToast("Lỗi kết nối máy chủ.", true);
            btnCreate.removeAttribute("disabled");
        } finally {
            btnCreate.innerText = originalText;
        }
    });
}

// 6. CÁC NÚT ĐIỀU KHIỂN AUTOMATION
function initActionButtons() {
    document.getElementById("btn-start").addEventListener("click", () => controlQueue("start"));
    document.getElementById("btn-stop").addEventListener("click", () => controlQueue("stop"));
    document.getElementById("btn-login").addEventListener("click", () => controlQueue("open-login"));
    document.getElementById("btn-switch-account")?.addEventListener("click", async () => {
        if (confirm("Bạn có chắc chắn muốn đăng xuất và đổi tài khoản Google / Gemini khác không?")) {
            await controlQueue("switch-account");
        }
    });
}

async function controlQueue(action) {
    try {
        const res = await fetch(`/api/${action}`, { method: "POST" });
        if (res.ok) {
            const data = await res.json();
            showToast(`Yêu cầu '${action}' thành công!`);
            pollStatus();
        } else {
            showToast(`Lỗi khi thực hiện yêu cầu '${action}'.`, true);
        }
    } catch (e) {
        showToast("Lỗi kết nối máy chủ.", true);
    }
}

// 7. POLLING CẬP NHẬT TRẠNG THÁI (STATUS POLLING)
function startPolling() {
    // Chạy định kỳ mỗi 1.5s
    setInterval(pollStatus, 1500);
}

async function pollStatus() {
    try {
        const res = await fetch("/api/status");
        if (!res.ok) return;
        
        const data = await res.json();
        updateUI(data);
    } catch (e) {
        console.error("Lỗi polling status:", e);
        document.getElementById("server-indicator").className = "status-indicator";
        document.getElementById("connection-text").innerText = "Mất kết nối API";
    }
}

// 8. CẬP NHẬT GIAO DIỆN (UI UPDATE LOGIC)
function updateUI(data) {
    // Cập nhật kết nối Server
    const serverIndicator = document.getElementById("server-indicator");
    serverIndicator.className = "status-indicator connected";
    document.getElementById("connection-text").innerText = "Đã kết nối";

    // Cập nhật Badge trạng thái Browser
    const browserStatus = document.getElementById("browser-status");
    browserStatus.className = `badge ${data.status}`;
    browserStatus.innerText = data.status.toUpperCase();

    // Cập nhật Live View Screenshot
    const imgScreenshot = document.getElementById("browser-screenshot");
    const overlay = document.getElementById("live-overlay");
    const overlayText = document.getElementById("overlay-status-text");

    if (data.screenshot) {
        imgScreenshot.src = `data:image/jpeg;base64,${data.screenshot}`;
        imgScreenshot.classList.remove("screenshot-placeholder");
    }

    // Hiển thị Overlay trạng thái trình duyệt nếu cần
    if (data.status === "waiting_login") {
        overlay.classList.add("active");
        overlayText.innerText = "Yêu cầu đăng nhập Google Chrome";
    } else if (data.status === "idle" && !data.screenshot) {
        overlay.classList.add("active");
        overlayText.innerText = "Trình duyệt đang chờ...";
    } else {
        overlay.classList.remove("active");
    }

    // Cập nhật Danh sách Hàng đợi (Queue)
    updateQueueList(data.queue, data.current_task_id);

    // Phát hiện xem có nhiệm vụ nào vừa chuyển từ chạy sang hoàn thành để reload gallery
    if (lastStatusResponse) {
        const previouslyRunning = lastStatusResponse.queue.some(t => t.status !== "completed" && t.status !== "failed");
        const currentlyRunning = data.queue.some(t => t.status !== "completed" && t.status !== "failed");
        if (previouslyRunning && !currentlyRunning) {
            // Vừa chạy xong hết, tải lại video gallery
            loadVideos();
        }
    }
    lastStatusResponse = data;
}

// 9. CẬP NHẬT BẢNG HÀNG ĐỢI NHIỆM VỤ
function updateQueueList(queue, currentTaskId) {
    latestQueueList = queue || [];
    const container = document.getElementById("queue-list");
    if (!queue || queue.length === 0) {
        container.innerHTML = '<div class="empty-state">Không có nhiệm vụ nào trong hàng đợi.</div>';
        return;
    }

    let html = "";
    queue.forEach(task => {
        const isRunning = currentTaskId && task.id === currentTaskId;
        const isActive = isRunning || (task.status !== "pending" && task.status !== "completed" && task.status !== "failed");
        const activeClass = isActive ? "active" : "";
        const progressPercent = task.progress || 0;
        
        let errorMsgHtml = "";
        if (task.error) {
            errorMsgHtml = `
                <div class="task-error-container" style="margin-top:8px; display:flex; align-items:flex-start; justify-content:space-between; background:#fff2f2; border:1px solid #ffd1d1; padding:6px 10px; border-radius:4px; gap:8px;">
                    <div class="task-error-text" style="color:var(--danger-color);font-size:0.8rem;word-break:break-word;flex:1;text-align:left;">Lỗi: ${task.error}</div>
                    <button onclick="copyErrorToClipboard('${task.id}')" class="btn-task-action btn-copy-error" style="padding:2px 6px; font-size:0.72rem; border-radius:3px; background:#fff; border:1px solid #ffd1d1; color:var(--danger-color); cursor:pointer; font-weight:500;" title="Copy log lỗi">📋 Copy</button>
                </div>
            `;
        }

        const canEdit = (task.status === "pending" || task.status === "failed") && !isRunning;
        const canRetry = task.status !== "pending" && !isRunning;
        const hasCaption = !!(task.caption || task.hashtags);
        
        let actionsHtml = `
            <div class="task-actions">
                ${hasCaption ? `<button onclick="copyTaskCaption('${task.id}')" class="btn-task-action btn-copy-caption" style="background:#4f46e5; color:#fff;" title="Sao chép bài đăng">📋 Copy Post</button>` : ''}
                ${canEdit ? `<button onclick="editTaskPrompt('${task.id}')" class="btn-task-action btn-edit" title="Sửa thông tin">✏️ Sửa</button>` : ''}
                ${canRetry ? `<button onclick="retryTask('${task.id}')" class="btn-task-action btn-retry" title="Chạy lại">🔄 Chạy lại</button>` : ''}
                <button onclick="deleteTask('${task.id}', '${task.status}')" class="btn-task-action btn-delete" title="Xóa nhiệm vụ">🗑️ Xóa</button>
            </div>
        `;

        html += `
            <div class="queue-item ${activeClass} ${task.status}">
                <div class="queue-item-header">
                    <span class="task-id">ID: ${task.id.substring(0, 8)}... (${task.duration}s | ${task.ratio || '9:16'})</span>
                    <span class="task-status ${task.status}">${task.status.toUpperCase()}</span>
                </div>
                <div class="task-desc">${task.user_description}</div>
                <div class="progress-container">
                    <div class="progress-bar" style="width: ${progressPercent}%"></div>
                </div>
                <div class="task-info-footer">
                    <span>Tiến trình: ${progressPercent}%</span>
                    <span>Ảnh: ${task.images.length}</span>
                </div>
                ${errorMsgHtml}
                ${actionsHtml}
            </div>
        `;
    });
    
    container.innerHTML = html;
}

// 10. TẢI VÀ HIỂN THỊ THƯ VIỆN VIDEO
async function loadVideos() {
    const grid = document.getElementById("video-grid");
    try {
        const res = await fetch("/api/videos");
        if (!res.ok) return;
        
        const videos = await res.json();
        if (videos.length === 0) {
            grid.innerHTML = '<div class="empty-state">Chưa có video nào được tạo thành công.</div>';
            return;
        }

        let html = "";
        videos.forEach((video, index) => {
            html += `
                <div class="video-item" data-index="${index}">
                    <div class="video-wrapper" data-url="${video.url}">
                        <video src="${video.url}" preload="metadata"></video>
                    </div>
                    <div class="video-info">
                        <div class="video-name" title="${video.filename}">${video.filename}</div>
                        <div class="video-card-actions" style="display:flex; gap:6px; margin-top:4px;">
                            <a href="${video.url}" download class="btn-download" style="flex:1; text-align:center;">💾 Tải về</a>
                            <button class="btn-copy-card" data-index="${index}" style="padding:6px 10px; font-size:0.75rem; background:#4f46e5; color:white; border:none; border-radius:var(--border-radius-sm); cursor:pointer; font-weight:600; transition:all 0.2s ease;" title="Sao chép bài đăng">📋 Copy</button>
                            <button class="btn-delete-card" data-index="${index}" style="padding:6px 10px; font-size:0.75rem; background:#ef4444; color:white; border:none; border-radius:var(--border-radius-sm); cursor:pointer; font-weight:600; transition:all 0.2s ease;" title="Xóa video này">🗑️ Xóa</button>
                        </div>
                    </div>
                </div>
            `;
        });
        grid.innerHTML = html;

        // Sự kiện click mở modal, copy bài đăng và xóa video trực tiếp từ thẻ video
        grid.querySelectorAll(".video-item").forEach((item, index) => {
            const wrapper = item.querySelector(".video-wrapper");
            const btnCopyCard = item.querySelector(".btn-copy-card");
            const btnDeleteCard = item.querySelector(".btn-delete-card");
            const videoData = videos[index];
            
            if (wrapper && videoData) {
                wrapper.addEventListener("click", () => {
                    openVideoModal(videoData);
                });
            }

            if (btnCopyCard && videoData) {
                btnCopyCard.addEventListener("click", (e) => {
                    e.stopPropagation();
                    if (videoData.caption || videoData.hashtags) {
                        const fullCopy = `${videoData.caption || ''}\n\n${videoData.hashtags || ''}`.trim();
                        copyTextToClipboard(fullCopy).then(() => {
                            showToast("📋 Đã sao chép Bài đăng & Hashtags!");
                        }).catch(() => {
                            showToast("Không thể tự động sao chép.", true);
                        });
                    } else {
                        showToast("Chưa có Caption đính kèm cho video này.", true);
                    }
                });
            }

            if (btnDeleteCard && videoData) {
                btnDeleteCard.addEventListener("click", (e) => {
                    e.stopPropagation();
                    deleteVideo(videoData.filename);
                });
            }
        });
    } catch (e) {
        console.error("Lỗi nạp thư viện video:", e);
    }
}

// 10.5. KHỞI TẠO VÀ ĐIỀU KHIỂN MODAL XEM VIDEO
function initVideoModal() {
    const modal = document.getElementById("video-modal");
    const closeBtn = document.getElementById("modal-close");
    const player = document.getElementById("modal-video-player");
    
    if (!modal || !closeBtn || !player) return;
    
    const closeModal = () => {
        modal.classList.remove("show");
        player.pause();
        const source = document.getElementById("modal-video-source");
        if (source) {
            source.setAttribute("src", "");
        }
        player.load();
    };

    closeBtn.addEventListener("click", closeModal);
    modal.addEventListener("click", (e) => {
        if (e.target === modal) {
            closeModal();
        }
    });
}

function openVideoModal(videoData) {
    const modal = document.getElementById("video-modal");
    const player = document.getElementById("modal-video-player");
    const source = document.getElementById("modal-video-source");
    const captionBox = document.getElementById("modal-caption-box");
    const captionText = document.getElementById("modal-caption-text");
    const hashtagsText = document.getElementById("modal-hashtags-text");
    
    const btnCopyAll = document.getElementById("btn-copy-all");
    const btnCopyCaption = document.getElementById("btn-copy-caption");
    const btnCopyHashtags = document.getElementById("btn-copy-hashtags");
    const btnDeleteModal = document.getElementById("btn-delete-modal-video");

    const url = typeof videoData === "string" ? videoData : videoData.url;
    
    if (!modal || !player || !source) return;
    
    source.setAttribute("src", url);
    player.load();

    if (btnDeleteModal && typeof videoData === "object" && videoData.filename) {
        btnDeleteModal.onclick = () => {
            deleteVideo(videoData.filename);
        };
    }

    // Luôn hiển thị captionBox trong modal
    if (captionBox) captionBox.style.display = "flex";

    if (typeof videoData === "object") {
        if (captionText) captionText.innerText = videoData.caption || "(Chưa có bài đăng quảng cáo)";
        if (hashtagsText) hashtagsText.innerText = videoData.hashtags || "";

        if (btnCopyAll) {
            btnCopyAll.onclick = () => {
                const fullCopy = `${videoData.caption || ''}\n\n${videoData.hashtags || ''}`.trim();
                if (!fullCopy) {
                    showToast("Chưa có thông tin để sao chép.", true);
                    return;
                }
                copyTextToClipboard(fullCopy).then(() => {
                    showToast("📋 Đã sao chép Bài đăng & Hashtags!");
                }).catch(() => {
                    showToast("Lỗi khi sao chép tự động.", true);
                });
            };
        }
        if (btnCopyCaption) {
            btnCopyCaption.onclick = () => {
                const captionOnly = (videoData.caption || '').trim();
                if (!captionOnly) {
                    showToast("Không có Caption để sao chép.", true);
                    return;
                }
                copyTextToClipboard(captionOnly).then(() => {
                    showToast("📝 Đã sao chép Caption!");
                }).catch(() => {
                    showToast("Lỗi khi sao chép tự động.", true);
                });
            };
        }
        if (btnCopyHashtags) {
            btnCopyHashtags.onclick = () => {
                const hashtagsOnly = (videoData.hashtags || '').trim();
                if (!hashtagsOnly) {
                    showToast("Không có Hashtags để sao chép.", true);
                    return;
                }
                copyTextToClipboard(hashtagsOnly).then(() => {
                    showToast("🏷️ Đã sao chép Hashtags!");
                }).catch(() => {
                    showToast("Lỗi khi sao chép tự động.", true);
                });
            };
        }
    }
    
    // Tự động căn chỉnh kích thước ngang/dọc dựa trên kích thước video thực tế
    const tempVideo = document.createElement("video");
    tempVideo.src = url;
    tempVideo.addEventListener("loadedmetadata", () => {
        const modalContent = modal.querySelector(".modal-content");
        if (modalContent) {
            if (tempVideo.videoWidth > tempVideo.videoHeight) {
                modalContent.classList.add("landscape");
            } else {
                modalContent.classList.remove("landscape");
            }
        }
    });

    modal.classList.add("show");
    player.play().catch(err => console.log("Tự động phát bị chặn:", err));
}

// 10.6. HÀM XÓA VIDEO
async function deleteVideo(filename) {
    if (!confirm(`Bạn có chắc chắn muốn xóa video '${filename}' không?\nVideo và dữ liệu đính kèm sẽ bị xóa vĩnh viễn.`)) {
        return;
    }
    try {
        const res = await fetch(`/api/videos/${encodeURIComponent(filename)}`, {
            method: "DELETE"
        });
        if (res.ok) {
            showToast("🗑️ Đã xóa video thành công!");
            const modal = document.getElementById("video-modal");
            if (modal && modal.classList.contains("show")) {
                document.getElementById("modal-close")?.click();
            }
            loadVideos();
        } else {
            const data = await res.json();
            showToast(`Lỗi khi xóa video: ${data.detail || 'Không xác định'}`, true);
        }
    } catch (e) {
        showToast("Lỗi kết nối máy chủ khi xóa video.", true);
    }
}

// 11. ĐƯA RA THÔNG BÁO NHANH (TOAST)
function showToast(message, isError = false) {
    const toast = document.getElementById("toast");
    toast.innerText = message;
    
    if (isError) {
        toast.style.borderColor = "var(--danger-color)";
    } else {
        toast.style.borderColor = "var(--primary-color)";
    }
    
    toast.classList.add("show");
    
    // Tự động ẩn sau 3s
    setTimeout(() => {
        toast.classList.remove("show");
    }, 3000);
}

// 12. CƠ CHẾ KÉO GIÃN 2 CỘT THỦ CÔNG
function initLayoutResizer() {
    const resizer = document.getElementById("layout-resizer");
    const leftCol = document.querySelector(".left-column");
    const container = document.querySelector(".main-content");
    
    if (!resizer || !leftCol || !container) return;

    let isResizing = false;

    resizer.addEventListener("mousedown", (e) => {
        isResizing = true;
        resizer.classList.add("resizing");
        document.body.style.cursor = "col-resize";
        document.body.style.userSelect = "none";
        
        // Tránh tình trạng bị iframe/overlay chiếm chuột khi drag
        const overlay = document.getElementById("live-overlay");
        if (overlay) overlay.style.pointerEvents = "none";
    });

    document.addEventListener("mousemove", (e) => {
        if (!isResizing) return;
        
        const containerRect = container.getBoundingClientRect();
        let newWidth = e.clientX - containerRect.left;
        
        // Ngưỡng kéo tối thiểu và tối đa (pixels)
        const minWidth = 320;
        const maxWidth = containerRect.width - 450;
        
        if (newWidth < minWidth) newWidth = minWidth;
        if (newWidth > maxWidth) newWidth = maxWidth;
        
        const percentage = (newWidth / containerRect.width) * 100;
        leftCol.style.width = `${percentage}%`;
    });

    document.addEventListener("mouseup", () => {
        if (isResizing) {
            isResizing = false;
            resizer.classList.remove("resizing");
            document.body.style.cursor = "";
            document.body.style.userSelect = "";
            
            const overlay = document.getElementById("live-overlay");
            if (overlay) overlay.style.pointerEvents = "";
            
            // Lưu lại tuỳ chọn của người dùng
            localStorage.setItem("leftColumnWidthPercent", leftCol.style.width);
        }
    });

    // Tải lại kích thước người dùng đã lưu
    const savedWidth = localStorage.getItem("leftColumnWidthPercent");
    if (savedWidth && window.innerWidth > 768) {
        leftCol.style.width = savedWidth;
    }
}

// 12. CÁC HÀM QUẢN LÝ NHIỆM VỤ (SỬA, XÓA, CHẠY LẠI, COPY CAPTION)
window.copyTaskCaption = (taskId) => {
    const task = latestQueueList.find(t => t.id === taskId);
    if (!task || (!task.caption && !task.hashtags)) {
        showToast("Chưa có nội dung Caption cho nhiệm vụ này.", true);
        return;
    }
    const fullCopy = `${task.caption || ''}\n\n${task.hashtags || ''}`.trim();
    navigator.clipboard.writeText(fullCopy).then(() => {
        showToast("📋 Đã sao chép Bài đăng & Hashtags vào bộ nhớ tạm!");
    }).catch(() => {
        showToast("Không thể tự động sao chép.", true);
    });
};

window.deleteTask = async (taskId, status) => {
    let confirmMsg = "Bạn có chắc muốn xóa nhiệm vụ này khỏi hàng đợi không?";
    const isActive = status !== "pending" && status !== "completed" && status !== "failed";
    if (isActive) {
        confirmMsg = "Nhiệm vụ này đang được chạy tự động! Nếu xóa, tiến trình đang chạy sẽ bị HỦY. Bạn có chắc muốn tiếp tục không?";
    }
    
    if (!confirm(confirmMsg)) return;
    
    try {
        const res = await fetch(`/api/tasks/${taskId}`, { method: "DELETE" });
        if (res.ok) {
            showToast("Đã xóa nhiệm vụ thành công!");
            pollStatus();
        } else {
            showToast("Không thể xóa nhiệm vụ này!", "error");
        }
    } catch (e) {
        showToast("Lỗi kết nối máy chủ!", "error");
    }
};

window.retryTask = async (taskId) => {
    try {
        const res = await fetch(`/api/tasks/${taskId}/retry`, { method: "POST" });
        if (res.ok) {
            showToast("Đã đưa nhiệm vụ trở lại hàng đợi xử lý!");
            pollStatus();
        } else {
            showToast("Không thể chạy lại nhiệm vụ này!", "error");
        }
    } catch (e) {
        showToast("Lỗi kết nối máy chủ!", "error");
    }
};

window.editTaskPrompt = async (taskId) => {
    const task = latestQueueList.find(t => t.id === taskId);
    if (!task) return;
    
    const newDesc = prompt("Sửa mô tả nội dung / chuyển động:", task.user_description);
    if (newDesc === null) return;
    const trimmedDesc = newDesc.trim();
    if (!trimmedDesc) {
        alert("Mô tả không được để trống!");
        return;
    }
    
    const newDurationStr = prompt("Sửa thời lượng (10, 20, 30):", task.duration);
    if (newDurationStr === null) return;
    const newDuration = parseInt(newDurationStr);
    if (isNaN(newDuration) || ![10, 20, 30].includes(newDuration)) {
        alert("Thời lượng không hợp lệ (chỉ chấp nhận 10, 20, hoặc 30)!");
        return;
    }
    
    const newRatio = prompt("Sửa tỷ lệ video (9:16 hoặc 16:9):", task.ratio || "9:16");
    if (newRatio === null) return;
    if (newRatio !== "9:16" && newRatio !== "16:9") {
        alert("Tỷ lệ không hợp lệ (chỉ chấp nhận 9:16 hoặc 16:9)!");
        return;
    }
    
    try {
        const res = await fetch(`/api/tasks/${taskId}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                user_description: trimmedDesc,
                duration: newDuration,
                ratio: newRatio
            })
        });
        if (res.ok) {
            showToast("Đã cập nhật thông tin nhiệm vụ!");
            pollStatus();
        } else {
            const err = await res.json();
            showToast(`Lỗi: ${err.detail || "Không thể sửa"}`, "error");
        }
    } catch (e) {
        showToast("Lỗi kết nối máy chủ!", "error");
    }
};

window.copyErrorToClipboard = async (taskId) => {
    const task = latestQueueList.find(t => t.id === taskId);
    if (!task || !task.error) return;
    
    copyTextToClipboard(task.error).then(() => {
        showToast("📋 Đã copy mã lỗi!");
    }).catch(() => {
        showToast("Không thể copy tự động!", "error");
    });
};

window.copyTaskCaption = function(taskId) {
    const task = latestQueueList.find(t => t.id === taskId);
    if (!task) return;
    const caption = task.caption || "";
    const hashtags = task.hashtags || "";
    if (!caption && !hashtags) {
        showToast("Nhiệm vụ này chưa có Caption/Hashtag.", true);
        return;
    }
    const fullText = `${caption}\n\n${hashtags}`.trim();
    copyTextToClipboard(fullText).then(() => {
        showToast("📋 Đã sao chép Bài đăng & Hashtags!");
    }).catch(err => {
        showToast("Không thể tự động sao chép.", true);
    });
};

// 13. HÀM TỰ ĐỘNG SAO CHÉP TƯƠNG THÍCH MỌI TRÌNH DUYỆT ĐIỆN THOẠI / HTTP
function copyTextToClipboard(text) {
    if (!text) return Promise.reject("Không có văn bản để sao chép");
    
    if (navigator.clipboard && window.isSecureContext) {
        return navigator.clipboard.writeText(text).catch(() => fallbackCopyTextToClipboard(text));
    } else {
        return fallbackCopyTextToClipboard(text);
    }
}

function fallbackCopyTextToClipboard(text) {
    return new Promise((resolve, reject) => {
        try {
            const textArea = document.createElement("textarea");
            textArea.value = text;
            textArea.style.position = "fixed";
            textArea.style.top = "0";
            textArea.style.left = "0";
            textArea.style.width = "2em";
            textArea.style.height = "2em";
            textArea.style.padding = "0";
            textArea.style.border = "none";
            textArea.style.outline = "none";
            textArea.style.boxShadow = "none";
            textArea.style.background = "transparent";
            textArea.style.opacity = "0.01";
            document.body.appendChild(textArea);
            
            textArea.focus();
            textArea.select();
            
            if (navigator.userAgent.match(/ipad|iphone/i)) {
                const range = document.createRange();
                range.selectNodeContents(textArea);
                const selection = window.getSelection();
                selection.removeAllRanges();
                selection.addRange(range);
                textArea.setSelectionRange(0, 999999);
            }

            const successful = document.execCommand('copy');
            document.body.removeChild(textArea);
            if (successful) {
                resolve();
            } else {
                reject(new Error("execCommand copy failed"));
            }
        } catch (err) {
            reject(err);
        }
    });
}
