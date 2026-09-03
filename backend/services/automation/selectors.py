"""
Lưu trữ tập trung tất cả các CSS/XPath Selectors giao diện Google Gemini UI & Google Accounts.
"""

TEXTBOX_SELECTOR = "div[role='textbox'], [contenteditable='true']"

PLUS_BUTTON_SELECTOR = (
    "button[aria-label*='upload' i], button[aria-label*='tải' i], "
    "button[aria-label*='thêm' i], button[aria-label*='add' i], "
    "button[mattooltip*='Upload' i], button[mattooltip*='Tải' i]"
)

PLUS_BUTTON_FALLBACK_SELECTOR = (
    ".simplified-input-menu-container button, .leading-actions-wrapper button, [class*='input-menu'] button, button.plus-button"
)

MENU_UPLOAD_SELECTOR = (
    "button[role*='menuitem']:has-text('Tải lên từ máy tính'), "
    "button[role*='menuitem']:has-text('Upload from computer'), "
    "button[role*='menuitem']:has-text('Upload from this device'), "
    "button[role*='menuitem']:has-text('Tải tệp lên'), "
    "button[role*='menuitem']:has-text('Upload file'), "
    "button[role*='menuitem']:has-text('Tải lên'), "
    "button[role*='menuitem']:has-text('Upload'), "
    ".gem-menu-item-label:has-text('Tải lên từ máy tính'), "
    ".gem-menu-item-label:has-text('Upload from computer'), "
    ".gem-menu-item-label:has-text('Upload from this device'), "
    ".gem-menu-item-label:has-text('Tải tệp lên'), "
    ".gem-menu-item-label:has-text('Upload file'), "
    "button:has-text('Tải lên từ máy tính'), "
    "button:has-text('Upload from computer'), "
    "button:has-text('Upload from this device'), "
    "button:has-text('Tải tệp lên'), "
    "button:has-text('Upload file'), "
    "button:has-text('Tải lên'), "
    "button:has-text('Upload'), "
    "[role*='menu'] button:has-text('Tải lên từ máy tính'), "
    "[role*='menu'] button:has-text('Upload from computer'), "
    "[role*='menu'] button:has-text('Upload from this device'), "
    "[role*='menu'] button:has-text('Tải tệp lên'), "
    "[role*='menu'] button:has-text('Upload file'), "
    "[role*='menu'] span:has-text('Tải lên từ máy tính'), "
    "[role*='menu'] span:has-text('Upload from computer'), "
    "[role*='menu'] span:has-text('Upload from this device'), "
    "[role*='menu'] span:has-text('Tải tệp lên'), "
    "[role*='menu'] span:has-text('Upload file')"
)

IMAGE_BUTTON_SELECTORS = [
    "button:has(mat-icon:has-text('image'))",
    "button:has(mat-icon:has-text('add_photo_alternate'))",
    "button:has(mat-icon:has-text('photo'))",
    "button:has(mat-icon:has-text('insert_photo'))",
    "button:has(mat-icon[data-mat-icon-name*='image'])",
    "button:has(mat-icon[data-mat-icon-name*='photo'])"
]

CREATE_VIDEO_BUTTON_SELECTORS = [
    "[data-test-id='videos-side-nav-entry-button']",
    "gem-nav-list-item:has-text('Video')",
    "toolbox-drawer-item:has-text('Tạo video')",
    "toolbox-drawer-item:has-text('Create video')",
    "toolbox-drawer-item:has-text('Veo')",
    ".gem-menu-item-label:has-text('Tạo video')",
    ".gem-menu-item-label:has-text('Create video')",
    ".gem-menu-item-label:has-text('Veo')",
    "[role*='menuitem']:has-text('Tạo video')",
    "[role*='menuitem']:has-text('Create video')",
    "[role*='menuitem']:has-text('Veo')",
    "button[role='menuitemcheckbox']:has-text('Tạo video')",
    "button[role='menuitemcheckbox']:has-text('Create video')",
    "button:has-text('Tạo video')",
    "button:has-text('Create video')",
    "span:has-text('Tạo video')",
    "span:has-text('Create video')",
    "div:has-text('Tạo video')",
    "div:has-text('Create video')",
    "button[aria-label*='video' i]",
    "*[role*='menuitem']:has-text('video' i)"
]

TRY_BUTTON_SELECTORS = (
    "button:has-text('Dùng thử'), button:has-text('Try'), "
    "button:has-text('Get started'), button:has-text('Dùng thử ngay')"
)

RATIO_BUTTON_SELECTOR = (
    "button:has-text('16:9'), button:has-text('9:16'), "
    "button:has-text('ngang'), button:has-text('dọc'), "
    "[role='button']:has-text('16:9'), [role='button']:has-text('9:16'), "
    "[role='combobox']:has-text('16:9'), [role='combobox']:has-text('9:16'), "
    "*[role='button']:has-text('ngang'), *[role='button']:has-text('dọc')"
)

RATIO_9_16_SELECTORS = [
    "span:has-text('Dọc (9:16)')", "span:has-text('Portrait (9:16)')",
    "[role*='menuitem'] span:has-text('9:16')", "[role*='menuitem']:has-text('9:16')",
    "[role*='option'] span:has-text('9:16')", "[role*='option']:has-text('9:16')",
    "span:has-text('Dọc')", "span:has-text('Portrait')", "button:has-text('9:16')"
]

RATIO_16_9_SELECTORS = [
    "span:has-text('Ngang (16:9)')", "span:has-text('Landscape (16:9)')",
    "[role*='menuitem'] span:has-text('16:9')", "[role*='menuitem']:has-text('16:9')",
    "[role*='option'] span:has-text('16:9')", "[role*='option']:has-text('16:9')",
    "span:has-text('Ngang')", "span:has-text('Landscape')", "button:has-text('16:9')"
]

PROMPT_INPUT_SELECTOR = (
    "div[role='textbox'][data-placeholder*='video' i], "
    "div[role='textbox'][data-placeholder*='Mô tả video' i], "
    ".ql-editor[data-placeholder*='video' i], "
    "div[role='textbox'][aria-label*='Gemini' i], "
    "div[role='textbox'][aria-label*='Nhập câu lệnh' i], "
    "div[role='textbox']"
)

SEND_BUTTON_SELECTORS = (
    ".send-button-container button, "
    "button[type='submit']:has(mat-icon[data-mat-icon-name='arrow_upward']), "
    "button[type='submit']:has(mat-icon[fonticon='arrow_upward']), "
    "button:has(mat-icon[data-mat-icon-name='arrow_upward']), "
    "button:has(mat-icon[fonticon='arrow_upward']), "
    "button[aria-label*='Gửi tin nhắn' i], "
    "button[aria-label*='Send message' i], "
    "button[aria-label*='Gửi câu lệnh' i], "
    "button[aria-label*='Gửi lời nhắc' i], "
    "button[aria-label*='Gửi yêu cầu' i], "
    "button[aria-label*='Gửi truy vấn' i], "
    "button[aria-label*='Send prompt' i], "
    "button[aria-label='Gửi' i], "
    "button[aria-label='Send' i], "
    "button[aria-label*='Gửi' i], "
    "button[aria-label*='Send' i], "
    "button:has(mat-icon[data-mat-icon-name='send']), "
    "button:has(mat-icon[fonticon='send']), "
    "button:has(mat-icon:has-text('arrow_upward')), "
    "button:has(mat-icon:has-text('send')), "
    "button.send-button, "
    "button[mattooltip*='Gửi' i], "
    "button[mattooltip*='Send' i]"
)

PROGRESS_BAR_SELECTORS = [
    "mat-progress-bar", "uploader-file mat-spinner", "file-preview mat-spinner", "[role='progressbar']"
]

IMAGE_PREVIEW_SELECTORS = [
    "uploader-file", "file-preview", ".image-preview", ".preview-image",
    "[data-test-id*='file']", "img[src*='blob:']", "img[src*='googleusercontent']",
    "img[src*='data:image']", "button[aria-label*='Remove' i]", "button[aria-label*='Xóa' i]",
    "button[aria-label*='Gỡ' i]", "button[aria-label*='Delete' i]", "mat-chip",
    "[class*='attachment']", "[class*='thumbnail']", "[class*='preview'] img",
    "figure img", "div[class*='image'] img"
]

VIDEO_PLAYER_SELECTOR = "video"

DOWNLOAD_BUTTON_SELECTORS = (
    "button[aria-label*='Download' i], button[aria-label*='Tải' i], "
    "button[mattooltip*='Download' i], button[mattooltip*='Tải' i], a[download]"
)
