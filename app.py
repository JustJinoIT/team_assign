import streamlit as st
import json
import firebase_admin
from firebase_admin import credentials, firestore
from collections import defaultdict
import random
import pandas as pd

# ==== Firebase 초기화 ====
if not firebase_admin._apps:
    service_account_info = json.loads(st.secrets["firebase"]["service_account_json"])
    cred = credentials.Certificate(service_account_info)
    firebase_admin.initialize_app(cred)

db = firestore.client()

# ==== 함수: 참가자 불러오기 ====
def load_participants():
    docs = db.collection("participants").stream()
    return {doc.id: doc.to_dict() for doc in docs}

# ==== 함수: 아티클 불러오기 ====
def load_articles():
    docs = db.collection("articles").stream()
    result = defaultdict(list)
    for doc in docs:
        data = doc.to_dict()
        week = data.get("week")
        if week:
            result[str(week)].append(data)
    return dict(result)

# ==== 함수: 히스토리 불러오기 ====
def load_history():
    docs = db.collection("history").stream()
    return {doc.id: doc.to_dict() for doc in docs}

# ==== 함수: 출결 불러오기 ====
def load_attendance():
    docs = db.collection("attendance").stream()
    result = defaultdict(dict)
    for doc in docs:
        data = doc.to_dict()
        week = data.get("week")
        pid = data.get("participant_id")
        status = data.get("status")
        if week and pid:
            result[str(week)][pid] = status
    return dict(result)

# ==== 참가자 등록 ====
st.title("🧑‍🤝‍🧑 기본조 + 활동조 배정 프로그램 (Firebase 연동)")

# --- 1. 참가자 등록 ---
st.header("1. 참가자 등록")
with st.form("participant_form"):
    pid = st.text_input("고유 ID (예: jinho)")
    name = st.text_input("이름")
    submit = st.form_submit_button("등록")
    if submit and pid and name:
        db.collection("participants").document(pid).set({"name": name})
        st.success(f"✅ {name} 참가자 등록 완료")

# --- 주차 선택 통일 ---
selected_week = st.selectbox("주차 선택", list(range(1, 8)))

# --- 2. 주차별 아티클 등록 ---
st.header("2. 주차별 아티클 등록")

article_list_docs = db.collection("articles").where("week", "==", str(selected_week)).stream()
article_list = [doc.to_dict() for doc in article_list_docs]

if not article_list:
    st.warning(f"{selected_week}주차에 등록된 아티클이 없습니다.")
else:
    with st.form("article_form"):
        cols = st.columns(4)
        article_data = []
        article_ids = ['1', '2', '3', '4']  # 아티클 번호 1~4
        for i in range(4):
            with cols[i]:
                existing = next((a for a in article_list if a['id'] == article_ids[i]), {})
                title = st.text_input(f"{article_ids[i]}번 제목", value=existing.get("title", ""), key=f"art_title_{i}")
                link = st.text_input(f"{article_ids[i]}번 링크", value=existing.get("link", ""), key=f"art_link_{i}")
                article_data.append({"week": str(selected_week), "id": article_ids[i], "title": title, "link": link})
        if st.form_submit_button("아티클 저장"):
            arts = db.collection("articles").where("week", "==", str(selected_week)).stream()
            for doc in arts:
                doc.reference.delete()
            for art in article_data:
                if art["title"].strip():
                    db.collection("articles").add(art)
            st.success("✅ 아티클 저장 완료")

# --- 3. 출결 등록 ---
st.header("3. 출결 등록")

participants = load_participants()
attendance_history = load_attendance()

if f"attendance_{selected_week}" not in st.session_state:
    st.session_state[f"attendance_{selected_week}"] = {}

st.markdown("#### ⛔️ 불참자만 체크하세요 (출석자는 체크할 필요 없습니다)")

cols = st.columns(5)
for idx, (pid, pdata) in enumerate(participants.items()):
    col = cols[idx % 5]
    # 이전 저장된 출결 상태 반영 (불참_pre / absent_day / attending)
    prev_status = attendance_history.get(str(selected_week), {}).get(pid, "attending")
    is_absent = prev_status != "attending"
    checked = col.checkbox(f"{pdata['name']}", value=is_absent, key=f"absent_{selected_week}_{pid}")
    st.session_state[f"attendance_{selected_week}"][pid] = "absent_pre" if checked else "attending"

if st.button("✅ 출결 저장"):
    # 저장 전 기존 출결 삭제 (덮어쓰기 용)
    docs = db.collection("attendance").where("week", "==", str(selected_week)).stream()
    for doc in docs:
        doc.reference.delete()
    for pid, status in st.session_state[f"attendance_{selected_week}"].items():
        db.collection("attendance").add({
            "week": str(selected_week),
            "participant_id": pid,
            "status": status
        })
    st.success("출결 상태가 저장되었습니다.")

# --- 조 배정 함수 ---
def assign_groups(selected_week):
    attendance = load_attendance()
    participants = load_participants()
    articles = load_articles()

    present = [pid for pid, status in attendance.get(str(selected_week), {}).items() if status == "attending"]
    if not present:
        st.warning("출석한 참가자가 없습니다.")
        return None, None

    random.shuffle(present)

    # 기본조 4명 기준 조 개수 결정 (3명 최소화, 5명 허용)
    def split_base_groups(present):
        n = len(present)
        min_groups = max(1, n // 4)
        max_groups = min(6, n // 3)
        for g in range(min_groups, max_groups + 1):
            size = n // g
            rem = n % g
            if size == 4 or (size == 3 and rem == 0):
                groups = []
                idx = 0
                for i in range(g):
                    group_size = size + (1 if i < rem else 0)
                    groups.append(present[idx:idx + group_size])
                    idx += group_size
                return groups
        groups = [present[i:i + 4] for i in range(0, n, 4)]
        if len(groups) > 1 and len(groups[-1]) == 3:
            groups[-2].extend(groups[-1])
            groups.pop()
        return groups

    base_groups = split_base_groups(present)

    # 아티클 1,2,3,4번 기준으로 활동조 배정
    article_list = articles.get(str(selected_week), [])
    article_ids = [a['id'] for a in article_list if a['title'].strip() != ""]
    if len(article_ids) < 4:
        article_ids = ['1', '2', '3', '4']

    activity_groups = {aid: [] for aid in article_ids}
    base_to_activity = {}

    for group in base_groups:
        assigned_articles = set()
        base_to_activity_group = {}
        for i, pid in enumerate(group):
            if len(group) == 4:
                aid = article_ids[i]
            else:
                # 5명 조일 땐 겹칠 수 있음
                aid = random.choice(article_ids)
            base_to_activity_group[pid] = aid
            assigned_articles.add(aid)
            activity_groups[aid].append(pid)
        base_to_activity.update(base_to_activity_group)

    return base_groups, activity_groups, base_to_activity

# --- 4. 조 배정 ---
st.header("4. 조 자동 배정 (기본조 4~5명 + 활동조 배정)")

# 이력 로드
histories = load_history()
history_weeks = sorted(set(h['week'] for h in histories.values()), reverse=True)

if selected_week in history_weeks:
    if st.button(f"🔄 {selected_week}주차 조 배정 재실행"):
        base_groups, activity_groups, base_to_activity = assign_groups(selected_week)
        if base_groups is None:
            st.error("출석자가 없어 조를 배정할 수 없습니다.")
        else:
            # 기존 이력 삭제
            existing_histories = db.collection("history").where("week", "==", str(selected_week)).stream()
            for doc in existing_histories:
                doc.reference.delete()
            # 새 이력 저장
            for idx, group in enumerate(base_groups, start=1):
                for pid in group:
                    db.collection("history").add({
                        "week": str(selected_week),
                        "base_group": f"{idx}조",
                        "participant_id": pid
                    })
            for aid, members in activity_groups.items():
                for pid in members:
                    db.collection("history").add({
                        "week": str(selected_week),
                        "activity_group": aid,
                        "participant_id": pid
                    })
            st.success(f"{selected_week}주차 조 배정이 재실행되어 저장되었습니다.")
else:
    if st.button(f"🚀 {selected_week}주차 조 배정 실행"):
        base_groups, activity_groups, base_to_activity = assign_groups(selected_week)
        if base_groups is None:
            st.error("출석자가 없어 조를 배정할 수 없습니다.")
        else:
            # 기존 이력 삭제
            existing_histories = db.collection("history").where("week", "==", str(selected_week)).stream()
            for doc in existing_histories:
                doc.reference.delete()
            # 새 이력 저장
            for idx, group in enumerate(base_groups, start=1):
                for pid in group:
                    db.collection("history").add({
                        "week": str(selected_week),
                        "base_group": f"{idx}조",
                        "participant_id": pid
                    })
            for aid, members in activity_groups.items():
                for pid in members:
                    db.collection("history").add({
                        "week": str(selected_week),
                        "activity_group": aid,
                        "participant_id": pid
                    })
            st.success(f"{selected_week}주차 조 배정이 완료되었습니다.")

# --- 5. 조 배정 이력 확인 ---
st.header("5. 조 배정 이력 확인")

if not history_weeks:
    st.info("아직 조 배정 이력이 없습니다.")
else:
    view_week = st.selectbox("이력 확인 주차 선택", history_weeks)
    if view_week:
        base_group_members = defaultdict(list)
        activity_group_members = defaultdict(list)
        for h in histories.values():
            if h['week'] == view_week:
                if 'base_group' in h:
                    base_group_members[h['base_group']].append(h['participant_id'])
                if 'activity_group' in h:
                    activity_group_members[h['activity_group']].append(h['participant_id'])

        st.subheader("기본조")
        for bg, members in sorted(base_group_members.items(), key=lambda x: int(x[0].replace("조",""))):
            names_with_article = []
            for pid in members:
                name = participants.get(pid, {}).get("name", pid)
                # 아티클 번호 찾기 (기본조 멤버별 아티클 표시)
                article_num = "-"
                for aid, pids in activity_group_members.items():
                    if pid in pids:
                        article_num = aid
                        break
                names_with_article.append(f"{name}({article_num})")
            st.write(f"{bg}: " + ", ".join(names_with_article))

        st.subheader("활동조")
        for ag, members in sorted(activity_group_members.items()):
            names = ", ".join(participants.get(pid, {}).get("name", pid) for pid in members)
            st.write(f"{ag}: {names}")

# --- 6. 출결 이력 확인 (추가) ---
st.header("6. 출결 이력 확인")

attendance = load_attendance()
if not attendance:
    st.info("아직 출결 데이터가 없습니다.")
else:
    view_week_att = st.selectbox("출결 이력 확인 주차 선택", sorted(attendance.keys(), reverse=True))
    if view_week_att:
        att_status = attendance.get(view_week_att, {})
        st.markdown(f"### {view_week_att}주차 출결 상태")
        cols = st.columns(5)
        for idx, (pid, pdata) in enumerate(participants.items()):
            col = cols[idx % 5]
            status = att_status.get(pid, "출결 기록 없음")
            status_label = "✅ 출석" if status == "attending" else ("⛔ 사전불참" if status == "absent_pre" else ("🚫 당일불참" if status == "absent_day" else "출결 기록 없음"))
            col.markdown(f"{pdata['name']} - {status_label}")

# --- 7. 참가자 관리 (삭제 기능) ---
st.header("7. 참가자 관리 (삭제 가능)")
participants = load_participants()
del_pid = st.selectbox("삭제할 참가자 선택", options=["선택 안 함"] + list(participants.keys()))
if del_pid != "선택 안 함":
    if st.button("삭제"):
        db.collection("participants").document(del_pid).delete()
        st.success(f"{participants[del_pid]['name']} 참가자가 삭제되었습니다.")

# --- 8. 엑셀 업로드 (참가자 + 출결 반영) ---
st.header("8. 엑셀 업로드 (참가자 등록, 출결 및 기본조 반영)")
uploaded_file = st.file_uploader("엑셀 파일 (.xlsx) 업로드", type=["xlsx"])
if uploaded_file:
    df = pd.read_excel(uploaded_file)
    participants = load_participants()
    for _, row in df.iterrows():
        name = str(row.get("성명", "")).strip()
        if name:
            pid = name.lower().replace(" ", "")
            if pid not in participants:
                db.collection("participants").document(pid).set({"name": name})
    for week in range(1, 8):
        col = f"{week}주차"
        if col in df.columns:
            for _, row in df.iterrows():
                name = str(row.get("성명", "")).strip()
                pid = name.lower().replace(" ", "")
                val = str(row.get(col, "")).strip()
                if val == "불참":
                    status = "absent_pre"
                elif val == "-":
                    status = "absent_day"
                elif val.endswith("조"):
                    status = "attending"
                else:
                    status = "absent_pre"
                db.collection("attendance").add({
                    "week": str(week),
                    "participant_id": pid,
                    "status": status
                })
                if val.endswith("조"):
                    db.collection("history").add({
                        "week": str(week),
                        "base_group": val,
                        "participant_id": pid
                    })
    st.success("✅ 엑셀에서 참가자 및 출결, 기본조 반영 완료")
