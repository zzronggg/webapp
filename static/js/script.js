document.addEventListener('DOMContentLoaded', () => {
    const dropdowns = document.querySelectorAll('.custom-dropdown');

    dropdowns.forEach(dropdown => {
        const toggle = dropdown.querySelector('.dropdown-toggle');
        const menu = dropdown.querySelector('.dropdown-menu');

        // 點擊按鈕時顯示或隱藏選單
        toggle.addEventListener('click', () => {
            // 關閉其他開啟的下拉式選單
            dropdowns.forEach(d => {
                if (d !== dropdown) {
                    d.querySelector('.dropdown-menu').style.display = 'none';
                }
            });

            // 切換目前選單的顯示狀態
            menu.style.display = menu.style.display === 'block' ? 'none' : 'block';
        });

        // 點擊選單項目時的處理邏輯
        menu.addEventListener('click', (event) => {
            const selected = event.target.closest('li');
            if (selected) {
                const selectedValue = selected.getAttribute('data-value');
                if (selectedValue === 'other') {
                    const userInput = prompt('請輸入自訂選項:');
                    if (userInput) {
                        toggle.innerHTML = `${userInput}`;
                        toggle.setAttribute('data-value', userInput);
                    }
                } else {
                    toggle.innerHTML = selected.innerHTML;
                    toggle.setAttribute('data-value', selectedValue);
                }
                menu.style.display = 'none';
            }
        });
    });

    // 點擊其他地方時關閉所有開啟的下拉式選單
    document.addEventListener('click', (event) => {
        if (!event.target.closest('.custom-dropdown')) {
            dropdowns.forEach(dropdown => {
                dropdown.querySelector('.dropdown-menu').style.display = 'none';
            });
        }
    });

    // 修改圖片上傳處理邏輯
    const imageUploadInput = document.getElementById('image-upload');
    const imagePreviewContainer = document.getElementById('image-preview');
    let uploadedImagePath = null;

    imageUploadInput.addEventListener('change', async function() {
        const file = this.files[0];
        if (file) {
            // 檢查文件大小
            if (file.size > 5 * 1024 * 1024) {
                imagePreviewContainer.innerHTML = `
                    <div class="upload-error">
                        <i class="fas fa-exclamation-circle"></i>
                        <span>圖片大小不能超過 5MB</span>
                    </div>
                `;
                return;
            }

            // 檢查文件類型
            const fileType = file.type.toLowerCase();
            const allowedTypes = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif'];
            if (!allowedTypes.includes(fileType)) {
                imagePreviewContainer.innerHTML = `
                    <div class="upload-error">
                        <i class="fas fa-exclamation-circle"></i>
                        <span>只支援 JPG、PNG 和 GIF 格式</span>
                    </div>
                `;
                return;
            }

            // 顯示上傳中狀態
            imagePreviewContainer.innerHTML = `
                <div class="upload-loading">
                    <i class="fas fa-spinner fa-spin"></i>
                    <span>上傳中...</span>
                </div>
            `;

            try {
                const formData = new FormData();
                formData.append('file', file);

                const response = await fetch('/upload-image/', {
                    method: 'POST',
                    body: formData
                });

                const result = await response.json();

                if (result.success) {
                    uploadedImagePath = result.file_path;
                    imagePreviewContainer.innerHTML = `
                        <img src="${result.file_path}" alt="預覽圖片">
                        <div class="upload-success">
                            <i class="fas fa-check-circle"></i>
                            <span>上傳成功!</span>
                        </div>
                    `;
                } else {
                    throw new Error(result.error);
                }
            } catch (error) {
                imagePreviewContainer.innerHTML = `
                    <div class="upload-error">
                        <i class="fas fa-exclamation-circle"></i>
                        <span>上傳失敗: ${error.message}</span>
                    </div>
                `;
            }
        }
    });

    // 添加字數計數功能
    const textarea = document.getElementById('image-description');
    const charCount = document.getElementById('char-count');

    textarea.addEventListener('input', () => {
        const count = textarea.value.length;
        charCount.textContent = count;
    });

    // 修改提交按鈕邏輯，加入描述文字
    document.getElementById('submit-btn').addEventListener('click', async () => {
        const platformToggle = document.getElementById('platform-toggle');
        const lengthToggle = document.getElementById('length-toggle');
        const styleToggle = document.getElementById('style-toggle');
        const resultBox = document.getElementById('result-box');

        // 檢查是否所有選項都已選擇
        if (!platformToggle.dataset.value || !lengthToggle.dataset.value || !styleToggle.dataset.value) {
            alert('請確保所有選項都已選擇！');
            return;
        }

        // 檢查是否已上傳圖片
        if (!uploadedImagePath) {
            alert('請先上傳圖片！');
            return;
        }

        try {
            // 添加生成中的提示
            resultBox.innerHTML = `
                <div class="generating">
                    <div class="loading-spinner"></div>
                    <p>AI 正在為您生成文案...</p>
                </div>
            `;

            const formData = new FormData();
            formData.append('platform', platformToggle.dataset.value);
            formData.append('length', lengthToggle.dataset.value);
            formData.append('style', styleToggle.dataset.value);
            formData.append('image_path', uploadedImagePath);
            
            // 添加描述文字（如果有的話）
            const description = document.getElementById('image-description').value;
            if (description.trim()) {
                formData.append('description', description);
            }

            const response = await fetch('/generate-post/', {
                method: 'POST',
                body: formData
            });

            const result = await response.json();

            if (result.success) {
                resultBox.innerHTML = `
                    <div class="result-content">
                        <p>${result.content}</p>
                        <img src="${uploadedImagePath}" alt="上傳的圖片">
                    </div>
                `;
            } else {
                throw new Error(result.error);
            }
        } catch (error) {
            resultBox.innerHTML = `
                <div class="error-message">
                    <i class="fas fa-exclamation-circle"></i>
                    <span>生成失敗: ${error.message}</span>
                </div>
            `;
        }
    });

    // 修改重置按鈕邏輯，清空描述文字
    document.getElementById('reset-btn').addEventListener('click', () => {
        document.getElementById('platform-toggle').innerHTML = '<i class="fas fa-globe"></i> 選擇平台';
        document.getElementById('platform-toggle').removeAttribute('data-value');

        document.getElementById('length-toggle').innerHTML = '<i class="fas fa-pen"></i> 選擇字數';
        document.getElementById('length-toggle').removeAttribute('data-value');

        document.getElementById('style-toggle').innerHTML = '<i class="fas fa-palette"></i> 選擇風格';
        document.getElementById('style-toggle').removeAttribute('data-value');

        document.getElementById('result-box').innerHTML = '';
        uploadedImagePath = null;
        imagePreviewContainer.innerHTML = '<p>圖片預覽將顯示在此處</p>';
        document.getElementById('image-description').value = '';
        document.getElementById('char-count').textContent = '0';
    });

    // 添加響應式處理
    function handleResponsive() {
        const isMobile = window.innerWidth <= 768;
        const dropdownMenus = document.querySelectorAll('.dropdown-menu');
        
        dropdownMenus.forEach(menu => {
            // 在手機版中，點擊後自動關閉選單
            if (isMobile) {
                menu.addEventListener('click', () => {
                    menu.style.display = 'none';
                }, { once: true });
            }
        });
    }

    // 監聽視窗大小變化
    window.addEventListener('resize', handleResponsive);
    handleResponsive(); // 初始化時執行一次

    // 修改圖片預覽的響應式處理
    function adjustImagePreview() {
        const preview = document.querySelector('.image-preview img');
        if (preview) {
            const isMobile = window.innerWidth <= 480;
            preview.style.height = isMobile ? '200px' : '300px';
        }
    }

    // 在圖片載入後調整大小
    imageUploadInput.addEventListener('change', function() {
        // ... 原有的上傳邏輯 ...
        if (file) {
            const reader = new FileReader();
            reader.onload = function(e) {
                const img = new Image();
                img.onload = function() {
                    adjustImagePreview();
                }
                img.src = e.target.result;
            }
            reader.readAsDataURL(file);
        }
    });

    window.addEventListener('resize', adjustImagePreview);
});

