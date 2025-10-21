import os

def is_text_file(file_path, blocksize=512):
    """判断文件是否是文本文件"""
    try:
        with open(file_path, 'rb') as f:
            block = f.read(blocksize)
            if b'\0' in block:  # 若包含空字节则视为二进制
                return False
        return True
    except Exception:
        return False

def search_word_in_text_files(root_dir, keyword="迭代"):
    """递归搜索目录下所有文本文件，找出包含指定关键字的文件"""
    matched_files = []
    for dirpath, _, filenames in os.walk(root_dir):
        for filename in filenames:
            file_path = os.path.join(dirpath, filename)
            if not is_text_file(file_path):
                continue
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    if keyword in content:
                        matched_files.append(file_path)
                        print(f"✅ 找到关键字“{keyword}” -> {file_path}")
            except Exception as e:
                print(f"⚠️ 无法读取 {file_path}: {e}")
    return matched_files

if __name__ == "__main__":
    folder = "."
    results = search_word_in_text_files(folder, "迭代")
    print("\n====== 搜索结果 ======")
    if results:
        for f in results:
            print(f)
    else:
        print("未找到包含“迭代”的文件。")
