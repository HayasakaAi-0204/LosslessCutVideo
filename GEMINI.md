Thư mục gốc của dự án là thư mục chứa file GEMINI.md này.

Bạn được tự chủ tạo, sửa, xóa file, refactor, cài dependencies,
chạy terminal, kiểm thử và xây dựng ứng dụng trong dự án.
Không cần xin xác nhận cho các thao tác nằm trong phạm vi này.

Mọi thay đổi dữ liệu dự án phải nằm trong thư mục gốc:
- Python packages cài vào .venv bằng interpreter của .venv.
- FFmpeg và FFprobe portable đặt trong tools/.
- Cache, file tạm, log và output đặt trong các thư mục con của dự án.
- Cấu hình biến môi trường cho tiến trình hiện tại, không sửa toàn hệ thống.

Không sửa Registry, PATH hệ thống, Git config toàn cục hoặc cài package
Python toàn cục. Không tạo worktree hoặc sử dụng junction/symlink để
ghi ra ngoài dự án. Không thay đổi quyền để vượt qua sandbox.

Nếu một thao tác cần quyền ngoài phạm vi, bỏ thao tác đó và báo rõ
trở ngại; tiếp tục những phần có thể hoàn thành trong dự án.

Ứng dụng viết bằng Python, ưu tiên PySide6 cho giao diện và FFmpeg/FFprobe
cho xử lý media. Giữ giao diện phản hồi khi xử lý video.

Khi phát triển, xuất kết quả thành file mới và bảo vệ video nguồn.
Chỉ báo hoàn thành sau khi đã chạy các kiểm tra phù hợp; ghi rõ phần
chưa kiểm chứng.