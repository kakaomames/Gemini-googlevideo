import subprocess
import json
import re
import os
from flask import Flask, request, jsonify, abort

app = Flask(__name__)

# --- curlコマンド実行とデータ取得の関数 ---
def get_curl_data(video_id, itags_to_check): # 引数名をより分かりやすく変更
    """
    指定されたIDとitagでcurlコマンドを実行し、リダイレクト先のURLとファイルサイズを取得する。
    1MB未満の場合は最大3回リトライする。
    """
    base_urls = [
        "https://inv-us4-c.nadeko.net/latest_version",
        "https://inv-us2-c.nadeko.net/latest_version",
        "https://inv-ca1-c.nadeko.net/latest_version",
        "https://inv-eu3-c.nadeko.net/latest_version",
    ]
    results = []
    
    # itags_to_check がリストであることを確認
    if not isinstance(itags_to_check, list):
        itags_to_check = [itags_to_check] # 単一のitagが渡された場合に対応

    for base_url in base_urls:
        # ここで itags_to_check リストをループするように修正
        for itag in itags_to_check: # <-- ここが修正点
            url_to_fetch = f"{base_url}?id={video_id}&itag={itag}&check="
            
            for attempt in range(3): # 最大3回リトライ
                full_curl_command = ["curl", "-L", "-v", url_to_fetch]
                
                try:
                    # curl -L -v でリダイレクト先と詳細情報を取得
                    process_redir = subprocess.run(
                        full_curl_command,
                        capture_output=True,
                        text=True, # stdout, stderrをテキストとして取得
                        check=True # コマンドがエラーコードを返したら例外を発生させる
                    )
                    
                    # リダイレクト先のURLを正規表現で抽出
                    # LocationヘッダからURLを取得するのが一般的です
                    redirect_url_match = re.search(r"Location: (.*)\n", process_redir.stderr)
                    redirect_url = redirect_url_match.group(1).strip() if redirect_url_match else None

                    if not redirect_url:
                        print(f"[{video_id}][itag={itag}] リダイレクトURLが見つかりませんでした (Attempt {attempt + 1})")
                        # ログファイルに-vの出力を記録
                        with open(f"/tmp/curl_log_{video_id}_{itag}_{attempt + 1}.log", "a") as f:
                            f.write(f"--- No Redirect URL Found ---\n")
                            f.write(f"Command: {' '.join(full_curl_command)}\n")
                            f.write(f"STDOUT:\n{process_redir.stdout}\n")
                            f.write(f"STDERR:\n{process_redir.stderr}\n")
                        continue # 次の試行へ

                    # リダイレクト先のファイルサイズを取得
                    size_command = ["curl", "-s", "-o", "/dev/null", "-w", "%{size_download}", redirect_url]
                    process_size = subprocess.run(
                        size_command,
                        capture_output=True,
                        text=True,
                        check=True
                    )
                    file_size_bytes = int(process_size.stdout.strip())
                    file_size_mb = file_size_bytes / (1024 * 1024)

                    print(f"[{video_id}][itag={itag}] URL: {redirect_url}, Size: {file_size_mb:.2f} MB")

                    if file_size_mb < 1.0:
                        print(f"ファイルサイズが1MB未満です ({file_size_mb:.2f} MB)。再試行します (Attempt {attempt + 1})")
                        # ログファイルに-vの出力を記録
                        with open(f"/tmp/curl_log_{video_id}_{itag}_{attempt + 1}.log", "a") as f:
                            f.write(f"--- File Size < 1MB ---\n")
                            f.write(f"URL: {url_to_fetch}\n")
                            f.write(f"Redirect URL: {redirect_url}\n")
                            f.write(f"File Size: {file_size_mb:.2f} MB\n")
                            f.write(f"Command (Redirect): {' '.join(full_curl_command)}\n")
                            f.write(f"STDOUT (Redirect):\n{process_redir.stdout}\n")
                            f.write(f"STDERR (Redirect):\n{process_redir.stderr}\n")
                            f.write(f"Command (Size): {' '.join(size_command)}\n")
                            f.write(f"STDOUT (Size):\n{process_size.stdout}\n")
                        if attempt == 2: # 3回試行して全て1MB未満なら候補から外す
                            print(f"3回試行しましたが、全て1MB未満でした。このitagはスキップします。")
                            break # このitagのループを抜ける
                        continue # 再試行

                    results.append({"itag": str(itag), "url": redirect_url})
                    break # 成功したのでこのitagの試行は終了

                except subprocess.CalledProcessError as e:
                    print(f"curlコマンドの実行に失敗しました: {e}")
                    print(f"STDOUT: {e.stdout}")
                    print(f"STDERR: {e.stderr}")
                    # ログファイルにエラー情報を記録
                    with open(f"/tmp/curl_log_error_{video_id}_{itag}_{attempt + 1}.log", "a") as f:
                        f.write(f"--- CURL Command Error ---\n")
                        f.write(f"Command: {' '.join(full_curl_command)}\n")
                        f.write(f"Error Code: {e.returncode}\n")
                        f.write(f"STDOUT:\n{e.stdout}\n")
                        f.write(f"STDERR:\n{e.stderr}\n")
                    if attempt == 2:
                        print(f"3回試行しましたが、エラーが解決しませんでした。このitagはスキップします。")
                        break
                    continue
                except Exception as e:
                    print(f"予期せぬエラーが発生しました: {e}")
                    # ログファイルにエラー情報を記録
                    with open(f"/tmp/curl_log_unexpected_error_{video_id}_{itag}_{attempt + 1}.log", "a") as f:
                        f.write(f"--- Unexpected Error ---\n")
                        f.write(f"Error: {e}\n")
                        f.write(f"URL: {url_to_fetch}\n")
                    if attempt == 2:
                        break
                    continue
    return {"video": results}


# --- ルート定義 ---

@app.route('/id')
def show_usage():
    """
    /id パスにアクセスされた場合、APIの使い方をJSON形式で返します。
    """
    usage_data = {
        "jp": {
            "status": 200,
            "message": "このAPIは動画情報の取得に使用できます。",
            "使い方": "/id?v={動画ID} の形式でアクセスしてください。{動画ID}にはYouTubeなどの動画IDを指定します。itagパラメータは内部で自動的に試行されます。",
            "例": "/id?v=dQw4w9WgXcQ"
        },
        "en": {
            "status": 200,
            "message": "This API can be used to retrieve video information.",
            "usage": "Access in the format: /id?v={video_id}. Replace {video_id} with a video ID from platforms like YouTube. The itag parameter will be tried automatically internally.",
            "example": "/id?v=dQw4w9WgXcQ"
        }
    }
    return jsonify(usage_data), 200

@app.route('/id', methods=['GET'])
def get_video_info():
    """
    /id?v={id} パスにアクセスされた場合、動画情報を処理して返します。
    """
    video_id = request.args.get('v')

    if not video_id:
        return jsonify({
            "jp": {"status": 400, "error": "必須パラメータ 'v' が不足しています。例: /id?v=動画ID"},
            "en": {"status": 400, "error": "Missing required parameter 'v'. Example: /id?v=videoID"}
        }), 400

    print(f"Received request for video ID: {video_id}")
    
    # 試したいitagのリスト。これは具体的な要件によって調整してください。
    itags_to_check = [18, 22, 36, 37, 38, 82, 83, 84, 85, 137, 138, 248, 266, 313, 335, 336, 337] # 例
    
    # 修正された get_curl_data 関数を呼び出す
    result_data = get_curl_data(video_id, itags_to_check)
    
    if not result_data["video"]:
        return jsonify({
            "jp": {"status": 404, "error": f"動画ID {video_id} に対応する有効な動画が見つかりませんでした、または取得できませんでした。ログファイルを確認してください。"},
            "en": {"status": 404, "error": f"No valid video found or retrieved for video ID {video_id}. Please check log files."}
        }), 404
    
    return jsonify(result_data)

# --- エラーハンドリング ---
@app.errorhandler(404)
def not_found_error(error):
    """
    404 Not Found エラーが発生した場合のカスタムレスポンス。
    """
    return jsonify({
        "jp": {"status": 404, "error": "このパスは使用できません。正しいパスは /id または /id?v={動画ID} です。"},
        "en": {"status": 404, "error": "This path is not available. Correct paths are /id or /id?v={videoID}."}
    }), 404

# --- アプリケーションの実行 ---
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
