import os
import shutil
import subprocess
from mcp.server.fastmcp import FastMCP

# Khởi tạo MCP Server
mcp = FastMCP("LLM_RAG")

# Lấy đường dẫn từ file JSON cấu hình (env)
ALLOWED_DIRECTORY = os.environ.get("ALLOWED_DIRECTORY", os.getcwd())

def get_safe_path(relative_path: str) -> str:
    """Hàm bổ trợ để đảm bảo đường dẫn luôn nằm trong vùng an toàn."""
    clean_path = os.path.normpath(relative_path).lstrip("/")
    if clean_path.startswith(".."):
        raise ValueError("Không thể truy cập khu vực ngoài vùng cấu hình ALLOWED_DIRECTORY.")
    return os.path.join(ALLOWED_DIRECTORY, clean_path)

@mcp.tool()
def run_terminal_command(command: str, relative_path: str = "."):
    """
    Chạy một lệnh CMD/Terminal tại thư mục dự án hoặc thư mục con cụ thể.
    Ví dụ: command="pip install requests", command="python test.py"
    """
    try:
        # Xác định thư mục thực thi lệnh
        execution_dir = get_safe_path(relative_path)
        
        if not os.path.exists(execution_dir):
            return f"Lỗi: Thư mục thực thi không tồn tại: {relative_path}"

        # Thực thi lệnh hệ thống
        # text=True và errors='ignore' để xử lý tốt cả font tiếng Việt/UTF-8 trên CMD Windows
        result = subprocess.run(
            command,
            cwd=execution_dir,
            shell=True,
            capture_output=True,
            text=True,
            errors='ignore',
            timeout=60 # Giới hạn 60 giây tránh treo tool nếu lệnh chạy vô hạn
        )
        
        # Gom kết quả trả về
        output = []
        if result.stdout:
            output.append(f"--- [STDOUT] ---\n{result.stdout}")
        if result.stderr:
            output.append(f"--- [STDERR] ---\n{result.stderr}")
            
        if not output:
            return f"Lệnh đã thực thi thành công (Mã thoát: {result.returncode}), không có dữ liệu xuất ra."
            
        return "\n".join(output)

    except subprocess.TimeoutExpired:
        return f"Lỗi: Lệnh bị dừng do chạy quá thời gian quy định (Timeout 60s): {command}"
    except Exception as e:
        return f"Lỗi hệ thống khi thực thi lệnh: {str(e)}"

@mcp.tool()
def list_files(relative_path: str = "."):
    """Liệt kê danh sách file và folder trong thư mục dự án."""
    try:
        search_path = get_safe_path(relative_path)
        if not os.path.exists(search_path):
            return f"Lỗi: Đường dẫn không tồn tại: {relative_path}"
        return os.listdir(search_path)
    except Exception as e:
        return f"Lỗi: {str(e)}"

@mcp.tool()
def read_file(file_name: str):
    """Đọc nội dung của một file cụ thể."""
    try:
        file_path = get_safe_path(file_name)
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Lỗi không thể đọc file: {str(e)}"

@mcp.tool()
def write_file(file_name: str, content: str):
    """Ghi nội dung vào file. Tự động tạo file mới nếu chưa có, hoặc ghi đè nếu đã tồn tại."""
    try:
        file_path = get_safe_path(file_name)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Đã lưu/tạo file thành công: {file_name}"
    except Exception as e:
        return f"Lỗi khi ghi file: {str(e)}"

@mcp.tool()
def make_directory(dir_name: str):
    """Tạo một hoặc nhiều thư mục mới (tự động tạo thư mục lồng nhau nếu cần)."""
    try:
        dir_path = get_safe_path(dir_name)
        os.makedirs(dir_path, exist_ok=True)
        return f"Đã tạo thư mục thành công: {dir_name}"
    except Exception as e:
        return f"Lỗi khi tạo thư mục: {str(e)}"

@mcp.tool()
def delete_path(target_path: str):
    """Xóa một file hoặc một thư mục (bao gồm tất cả file/thư mục con bên trong)."""
    try:
        full_path = get_safe_path(target_path)
        if not os.path.exists(full_path):
            return f"Lỗi: Đường dẫn không tồn tại để xóa: {target_path}"
        
        if os.path.isdir(full_path):
            shutil.rmtree(full_path)
            return f"Đã xóa thư mục và toàn bộ nội dung bên trong: {target_path}"
        else:
            os.remove(full_path)
            return f"Đã xóa file thành công: {target_path}"
    except Exception as e:
        return f"Lỗi khi xóa: {str(e)}"

@mcp.tool()
def move_path(source_path: str, destination_path: str):
    """Di chuyển hoặc đổi tên file/thư mục từ vị trí cũ sang vị trí mới."""
    try:
        src = get_safe_path(source_path)
        dst = get_safe_path(destination_path)
        
        if not os.path.exists(src):
            return f"Lỗi: Vị trí nguồn không tồn tại: {source_path}"
            
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)
        return f"Đã di chuyển/đổi tên từ '{source_path}' sang '{destination_path}' thành công."
    except Exception as e:
        return f"Lỗi khi di chuyển: {str(e)}"

if __name__ == "__main__":
    mcp.run()