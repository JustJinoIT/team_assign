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

# ==== 데이터 로드 함수 ====
def load_participants():
    docs = db.collection("participants").stream()
    return {doc.id: doc.to_dict() for doc in docs}

def load_articles():
    docs = db.collection("articles").stream()
    result = defaultdict(list)
    for doc in docs:
        d = doc.to_dict()
        week = d.get("week")
        if week:
            result[str(week)].append(d)
    return dict(result)

def load_attendance():
    docs = db.collection("attendance").stream()
    result = defaultdict(dict)
    for doc in docs:
        d = doc.to_dict()
        week = d.get("week")
        pid = d.get("participant_id")
        status = d.get("status")
        if week and pid:
            result[str(week)][pid] = status
    return dict(result)

def load_history():
    docs = db.collection("history").stream()
    return {doc.id: doc.to_dict() for doc in docs}

# ==== 참가자 관리 ====
st.title("🧑‍🤝‍🧑 기본조 + 활동조 배정 프로그램 (Firebase 연동)")

with st.expander("👥 참가자 관리"):
    participants = load_participants()
    st.write(f"총 참가자 수: {len(participants)}")
    to_delete = []
    cols = st.columns([6,1])
    cols[0].write("이름 (ID)")
    cols[1].write("삭제")
    for pid, pdata in participants.items():
        cols = st.columns([6,1])
        cols[0].write(f"{pdata.get('name')} ({pid})")
        if cols[1].button("삭제", key=f"del_{pid}"):
            to_delete.append(pid)
    if to_delete:
        for pid in to_delete:
            db.collection("participants").document(pid).delete()
            # 출결 삭제
            att_docs = db.collection("attendance").where("participant_id", "==", pid).stream()
            for doc in att_docs:
                doc.reference.delete()
            # 이력 삭제
            hist_docs = db.collection("history").where("participant_id", "==", pid).stream()
            for doc in hist_docs:
                doc.reference.delete()
        st.success(f"{len(to_delete)}명 삭제 완료")
        st.experimental_rerun()

# ==== 참가자 등록 ====
st.header("1. 참가자 등록")
with st.form("participant_form"):
    pid = st.text_input("고유 ID (예: jinho)")
    name = st.text_input("이름")
    submit = st.form_submit_button("등록")
    if submit:
        if not pid or not name:
            st.error("ID와 이름을 모두 입력하세요.")
        else:
            db.collection("participants").document(pid).set({"name": name})
            st.success(f"✅ {name} 참가자 등록 완료")
            st.experimental_rerun()

# ==== 엑셀 업로드 (참가자 중복 등록 방지 + 출결, 기본조 반영) ====
st.subheader("📥 엑셀 업로드 (참가자 및 출결/기본조 반영)")
uploaded_file = st.file_uploader("엑셀(.xlsx) 업로드", type=["xlsx"])
if uploaded_file:
    df = pd.read_excel(uploaded_file)
    participants = load_participants()
    added = 0
    for _, row in df.iterrows():
        name = str(row.get("성명", "")).strip()
        if name:
            pid = name.lower().replace(" ", "")
            if pid not in participants:
                db.collection("participants").document(pid).set({"name": name})
                added += 1
    # 출결 및 기본조 반영
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
    st.success(f"✅ 엑셀 반영 완료 (신규 참가자 {added}명 추가됨)")

# ==== 아티클 관리 ====
st.header("2. 주차별 아티클 등록")
week = st.selectbox("주차 선택", list(range(1, 8)), key="article_week")
with st.form("article_form"):
    cols = st.columns(4)
    article_data = []
    for i in range(4):
        with cols[i]:
            title = st.text_input(f"{i+1}번 제목", key=f"art_title_{week}_{i}")
            link = st.text_input(f"{i+1}번 링크", key=f"art_link_{week}_{i}")
            article_data.append({"week": str(week), "id": chr(65+i), "title": title, "link": link})
    if st.form_submit_button("아티클 저장"):
        arts = db.collection("articles").where("week", "==", str(week)).stream()
        for doc in arts:
            doc.reference.delete()
        for art in article_data:
            if art['title'].strip() != "":
                db.collection("articles").add(art)
        st.success(f"✅ {week}주차 아티클 저장 완료")

# ==== 출결 관리 및 등록 ====
st.header("3. 출결 관리 및 등록")
selected_week = st.selectbox("출결 관리 주차 선택", list(range(1, 8)), key="attendance_week")
participants = load_participants()
attendance = load_attendance()
week_attendance = attendance.get(str(selected_week), {})

st.markdown("#### ⛔️ 불참(사전), 당일불참 체크 (출석은 체크 필요 없음)")

cols = st.columns(5)
for idx, (pid, pdata) in enumerate(participants.items()):
    col = cols[idx % 5]
    absent_pre_checked = week_attendance.get(pid) == "absent_pre"
    absent_day_checked = week_attendance.get(pid) == "absent_day"
    col.write(pdata["name"])
    absent_pre = col.checkbox("불참", key=f"absent_pre_{selected_week}_{pid}", value=absent_pre_checked)
    absent_day = col.checkbox("당일불참", key=f"absent_day_{selected_week}_{pid}", value=absent_day_checked)
    # 상호 배타적 체크 처리
    if absent_pre and absent_day:
        # 둘 다 체크 안 되도록 처리 (가장 최근 상태 반영)
        if st.session_state[f"absent_pre_{selected_week}_{pid}"] != absent_pre_checked:
            st.session_state[f"absent_day_{selected_week}_{pid}"] = False
        else:
            st.session_state[f"absent_pre_{selected_week}_{pid}"] = False

if st.button("✅ 출결 저장"):
    for pid in participants.keys():
        if st.session_state.get(f"absent_pre_{selected_week}_{pid}", False):
            status = "absent_pre"
        elif st.session_state.get(f"absent_day_{selected_week}_{pid}", False):
            status = "absent_day"
        else:
            status = "attending"
        db.collection("attendance").add({
            "week": str(selected_week),
            "participant_id": pid,
            "status": status
        })
    st.success("✅ 출결 저장 완료")

# ==== 조 배정 함수 ====

def assign_groups(selected_week):
    attendance = load_attendance()
    participants = load_participants()
    articles = load_articles()

    present = [pid for pid, status in attendance.get(str(selected_week), {}).items() if status == "attending"]
    if not present:
        st.warning("출석한 참가자가 없습니다.")
        return None, None

    random.shuffle(present)

    # 기본조 4명 우선 (5명 가능), 최소 3명 조 최소화
    def split_base_groups(present):
        n = len(present)
        min_groups = max(1, n // 4)
        max_groups = min(6, n // 3)  # 최대 6개 조 제한
        for g in range(min_groups, max_groups+1):
            size = n // g
            rem = n % g
            if size == 4 or (size == 3 and rem == 0):
                groups = []
                idx = 0
                for i in range(g):
                    group_size = size + (1 if i < rem else 0)
                    groups.append(present[idx:idx+group_size])
                    idx += group_size
                return groups
        groups = [present[i:i+4] for i in range(0, n, 4)]
        if len(groups) > 1 and len(groups[-1]) == 3:
            groups[-2].extend(groups[-1])
            groups.pop()
        return groups

    base_groups = split_base_groups(present)

    # 활동조: 아티클 4개 기준으로 배정
    article_list = articles.get(str(selected_week), [])
    article_ids = [a['id'] for a in article_list if a['title'].strip() != ""]
    if len(article_ids) < 4:
        article_ids = ['A','B','C','D']

    activity_groups = {aid: [] for aid in article_ids}
    base_to_activity = {}

    for group in base_groups:
        assigned_articles = set()
        base_to_activity_group = {}
        for i, pid in enumerate(group):
            if len(group) == 4:
                # 겹치지 않도록 순서대로
                aid = article_ids[i]
            else:
                # 5명 조일 경우 겹칠 수 있음, 최대 2명까지 제한 예시
                counts = {a: sum([1 for p in activity_groups[a] if p in group]) for a in article_ids}
                candidates = [a for a in article_ids if counts[a] < 2]
                if not candidates:
                    candidates = article_ids
                aid = random.choice(candidates)
            base_to_activity_group[pid] = aid
            assigned_articles.add(aid)
            activity_groups[aid].append(pid)
        base_to_activity.update(base_to_activity_group)

    return base_groups, activity_groups

# ==== 조 배정 실행/재실행 버튼 ====
st.header("4. 조 자동 배정 (기본조 4~5명 + 활동조 배정)")
histories_query = db.collection("history").where("week", "==", str(selected_week)).limit(1).stream()
has_history = any(True for _ in histories_query)

if has_history:
    if st.button("🔄 조 배정 재실행"):
        base_groups, activity_groups = assign_groups(selected_week)
        if base_groups is None:
            st.error("출석자가 없어 조를 배정할 수 없습니다.")
        else:
            histories = db.collection("history").where("week", "==", str(selected_week)).stream()
            for doc in histories:
                doc.reference.delete()
            for idx, group in enumerate(base_groups, start=1):
                for pid in group:
                    db.collection("history").add({
                        "week": str(selected_week),
                        "base_group": f"{idx}조",
                        "participant_id": pid
                    })
            for aid, pids in activity_groups.items():
                for pid in pids:
                    db.collection("history").add({
                        "week": str(selected_week),
                        "activity_group": aid,
                        "participant_id": pid
                    })
            st.success("🔄 조 배정 재실행 완료!")
else:
    if st.button("🚀 조 배정 실행"):
        base_groups, activity_groups = assign_groups(selected_week)
        if base_groups is None:
            st.error("출석자가 없어 조를 배정할 수 없습니다.")
        else:
            for idx, group in enumerate(base_groups, start=1):
                for pid in group:
                    db.collection("history").add({
                        "week": str(selected_week),
                        "base_group": f"{idx}조",
                        "participant_id": pid
                    })
            for aid, pids in activity_groups.items():
                for pid in pids:
                    db.collection("history").add({
                        "week": str(selected_week),
                        "activity_group": aid,
                        "participant_id": pid
                    })
            st.success("🚀 조 배정 실행 완료!")

# ==== 조 배정 이력 확인 ====
st.header("5. 조 배정 이력 확인")
history_docs = db.collection("history").where("week", "==", str(selected_week)).stream()
base_group_map = defaultdict(list)
activity_group_map = defaultdict(list)
participants = load_participants()

for doc in history_docs:
    d = doc.to_dict()
    pid = d.get("participant_id")
    pname = participants.get(pid, {}).get("name", pid)
    if "base_group" in d:
        base_group_map[d["base_group"]].append(pname)
    if "activity_group" in d:
        activity_group_map[d["activity_group"]].append(pname)

st.subheader("기본조")
if base_group_map:
    for bg, members in sorted(base_group_map.items()):
        st.write(f"**{bg}** : {', '.join(members)}")
else:
    st.write("기본조 배정 내역이 없습니다.")

st.subheader("활동조")
if activity_group_map:
    for ag, members in sorted(activity_group_map.items()):
        st.write(f"**{ag} 아티클** : {', '.join(members)}")
else:
    st.write("활동조 배정 내역이 없습니다.")

