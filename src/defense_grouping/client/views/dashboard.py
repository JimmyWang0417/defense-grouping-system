import flet as ft

from defense_grouping.client.session import SessionState


def dashboard_view(session: SessionState) -> ft.Control:
    role_labels = {
        "system_admin": "系统管理员",
        "academic_admin": "教务管理员",
        "teacher": "教师",
    }
    roles = "、".join(role_labels.get(role, role) for role in sorted(session.roles))
    return ft.Column(
        controls=[
            ft.Text("工作台", size=28, weight=ft.FontWeight.BOLD),
            ft.Text(f"欢迎，{session.username or '用户'}"),
            ft.Text(f"当前角色：{roles}"),
            ft.ResponsiveRow(
                controls=[
                    ft.Card(
                        content=ft.Container(
                            content=ft.Text("待处理任务将在此显示"), padding=20
                        ),
                        col={"xs": 12, "md": 6, "lg": 4},
                    ),
                    ft.Card(
                        content=ft.Container(
                            content=ft.Text("近期答辩活动将在此显示"), padding=20
                        ),
                        col={"xs": 12, "md": 6, "lg": 4},
                    ),
                ]
            ),
        ]
    )


def placeholder_view(title: str) -> ft.Control:
    return ft.Column(
        controls=[
            ft.Text(title, size=28, weight=ft.FontWeight.BOLD),
            ft.Text("该工作流将在下一实施阶段接入稳定 API。"),
        ]
    )
