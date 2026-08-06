class HelpMessage:
    @staticmethod
    def get_general_commands_text():
       commands_text = "> - **/review**: Yêu cầu đánh giá Pull Request của bạn.   \n" \
                "> - **/describe**: Cập nhật tiêu đề và mô tả PR dựa trên nội dung của PR.   \n" \
                "> - **/improve [--extended]**: Đề xuất cải tiến code. Chế độ mở rộng cung cấp phản hồi chất lượng cao hơn.   \n" \
                "> - **/ask \\<QUESTION\\>**: Đặt câu hỏi về PR.   \n" \
                "> - **/update_changelog**: Cập nhật changelog dựa trên nội dung của PR.   \n" \
                "> - **/help_docs \\<QUESTION\\>**: Cho một đường dẫn tài liệu (của repository này hoặc một repository khác), đặt câu hỏi.   \n" \
                "> - **/add_docs**: Sinh docstring cho các thành phần mới được đưa vào trong PR.   \n" \
                "> - **/generate_labels**: Sinh nhãn cho PR dựa trên nội dung của PR.   \n\n" \
                ">Xem [hướng dẫn công cụ](https://pr-agent-docs.codium.ai/tools/) để biết thêm chi tiết.\n" \
                ">Để xem danh sách các tham số cấu hình khả dụng, thêm một bình luận **/config**.   \n"
       return commands_text


    @staticmethod
    def get_general_bot_help_text():
        output = f"> Để gọi PR-Agent, thêm một bình luận sử dụng một trong các lệnh sau:  \n{HelpMessage.get_general_commands_text()} \n"
        return output

    @staticmethod
    def get_review_usage_guide():
        output ="**Tổng quan:**\n"
        output +=("Công cụ `review` quét các thay đổi code trong PR, và sinh ra một đánh giá PR bao gồm nhiều loại phản hồi khác nhau, như các vấn đề PR có thể xảy ra, các nguy cơ bảo mật và test liên quan trong PR. Có thể [thêm](https://pr-agent-docs.codium.ai/tools/review/#general-configurations) nhiều phản hồi hơn bằng cách cấu hình công cụ.\n\n"
                  "Công cụ có thể được kích hoạt [tự động](https://pr-agent-docs.codium.ai/usage-guide/automations_and_usage/#github-app-automatic-tools-when-a-new-pr-is-opened) mỗi khi một PR mới được mở, hoặc có thể được gọi thủ công bằng cách bình luận trên bất kỳ PR nào.\n")
        output +="""\
- Khi bình luận, để chỉnh sửa [cấu hình](https://github.com/Codium-ai/pr-agent/blob/main/pr_agent/settings/configuration.toml#L23) liên quan đến công cụ review (mục `pr_reviewer`), dùng mẫu sau:
```
/review --pr_reviewer.some_config1=... --pr_reviewer.some_config2=...
```
- Với một [file cấu hình](https://pr-agent-docs.codium.ai/usage-guide/configuration_options/), dùng mẫu sau:
```
[pr_reviewer]
some_config1=...
some_config2=...
```
    """

        output += f"\n\nXem [trang sử dụng](https://pr-agent-docs.codium.ai/tools/review/) review để có hướng dẫn đầy đủ về cách dùng công cụ này.\n\n"

        return output



    @staticmethod
    def get_describe_usage_guide():
        output = "**Tổng quan:**\n"
        output += "Công cụ `describe` quét các thay đổi code trong PR, và sinh ra một mô tả cho PR - tiêu đề, loại, tóm tắt, walkthrough và nhãn. "
        output += "Công cụ có thể được kích hoạt [tự động](https://pr-agent-docs.codium.ai/usage-guide/automations_and_usage/#github-app-automatic-tools-when-a-new-pr-is-opened) mỗi khi một PR mới được mở, hoặc có thể được gọi thủ công bằng cách bình luận trên một PR.\n"
        output += """\

Khi bình luận, để chỉnh sửa [cấu hình](https://github.com/Codium-ai/pr-agent/blob/main/pr_agent/settings/configuration.toml#L46) liên quan đến công cụ describe (mục `pr_description`), dùng mẫu sau:
```
/describe --pr_description.some_config1=... --pr_description.some_config2=...
```
Với một [file cấu hình](https://pr-agent-docs.codium.ai/usage-guide/configuration_options/), dùng mẫu sau:
```
[pr_description]
some_config1=...
some_config2=...
```
"""
        output += "\n\n<table>"

        # automation
        output += "<tr><td><details> <summary><strong> Bật\\tắt tự động hóa </strong></summary><hr>\n\n"
        output += """\
- Khi bạn cài app lần đầu, [chế độ mặc định](https://pr-agent-docs.codium.ai/usage-guide/automations_and_usage/#github-app-automatic-tools-when-a-new-pr-is-opened) cho công cụ describe là:
```
pr_commands = ["/describe", ...]
```
nghĩa là công cụ `describe` sẽ tự động chạy trên mọi PR.

- Marker là một cách khác để kiểm soát mô tả được sinh ra, nhằm trao quyền kiểm soát tối đa cho người dùng. Nếu bạn đặt:
```
pr_commands = ["/describe --pr_description.use_description_markers=true", ...]
```
công cụ sẽ thay thế mọi marker dạng `pr_agent:marker_name` trong mô tả PR bằng nội dung liên quan, trong đó `marker_name` là một trong các giá trị sau:
  - `type`: loại PR.
  - `summary`: tóm tắt PR.
  - `walkthrough`: walkthrough PR.
  - `diagram`: sơ đồ trình tự PR (nếu được bật).

Lưu ý rằng khi marker được bật, nếu mô tả PR ban đầu không chứa marker nào, công cụ sẽ không thay đổi mô tả.

"""
        output += "\n\n</details></td></tr>\n\n"

        # custom labels
        output += "<tr><td><details> <summary><strong> Nhãn tùy chỉnh </strong></summary><hr>\n\n"
        output += """\
Các nhãn mặc định của công cụ `describe` khá chung: [`Bug fix`, `Tests`, `Enhancement`, `Documentation`, `Other`].

Nếu bạn khai báo [nhãn tùy chỉnh](https://pr-agent-docs.codium.ai/tools/describe/#handle-custom-labels-from-the-repos-labels-page) trong trang nhãn của repo hoặc qua file cấu hình, bạn có thể có nhãn phù hợp với nhu cầu sử dụng của mình.
Ví dụ về nhãn tùy chỉnh:
- `Main topic:performance` - pr_agent:Chủ đề chính của PR này là performance
- `New endpoint` - pr_agent:Một endpoint mới đã được thêm trong PR này
- `SQL query` - pr_agent:Một câu SQL mới đã được thêm trong PR này
- `Dockerfile changes` - pr_agent:PR chứa thay đổi trong Dockerfile
- ...

Danh sách trên chỉ mang tính minh họa, nhằm gợi ý các khả năng khác nhau. Hãy định nghĩa nhãn tùy chỉnh phù hợp với repo và nhu cầu sử dụng của bạn.
Lưu ý rằng các nhãn không loại trừ nhau, nên bạn có thể thêm nhiều nhóm nhãn.
Hãy đảm bảo cung cấp tiêu đề phù hợp, và mô tả chi tiết, rõ ràng cho từng nhãn, để công cụ biết khi nào nên đề xuất nhãn đó.
"""
        output += "\n\n</details></td></tr>\n\n"

        # extra instructions
        output += "<tr><td><details> <summary><strong> Sử dụng chỉ dẫn bổ sung</strong></summary><hr>\n\n"
        output += '''\
Công cụ `describe` có thể được cấu hình với các chỉ dẫn bổ sung, để hướng dẫn model đưa ra phản hồi phù hợp với nhu cầu của dự án bạn.

Hãy viết chỉ dẫn cụ thể, rõ ràng và ngắn gọn. Với chỉ dẫn bổ sung, bạn chính là người ra lệnh cho model. Lưu ý rằng cấu trúc tổng thể của mô tả là cố định, và không thể thay đổi. Chỉ dẫn bổ sung có thể thay đổi nội dung hoặc phong cách của từng mục con trong mô tả PR.

Ví dụ về chỉ dẫn bổ sung:
```
[pr_description]
extra_instructions="""\
- Tiêu đề PR nên theo định dạng: '<PR type>: <title>'
- Tiêu đề nên ngắn gọn (tối đa 10 từ)
- ...
"""
```
Dùng dấu triple quote để viết chỉ dẫn nhiều dòng. Dùng dấu đầu dòng để chỉ dẫn dễ đọc hơn.
'''
        output += "\n\n</details></td></tr>\n\n"


        # general
        output += "\n\n<tr><td><details> <summary><strong> Thêm lệnh PR-Agent</strong></summary><hr> \n\n"
        output += HelpMessage.get_general_bot_help_text()
        output += "\n\n</details></td></tr>\n\n"

        output += "</table>"

        output += f"\n\nXem [trang sử dụng](https://pr-agent-docs.codium.ai/tools/describe/) describe để có hướng dẫn đầy đủ về cách dùng công cụ này.\n\n"

        return output

    @staticmethod
    def get_ask_usage_guide():
        output = "**Tổng quan:**\n"
        output += """\
Công cụ `ask` trả lời các câu hỏi về PR, dựa trên các thay đổi code trong PR.
Có thể gọi thủ công bằng cách bình luận trên bất kỳ PR nào:
```
/ask "..."
```

Lưu ý rằng công cụ này không có "bộ nhớ" về các câu hỏi trước, và trả lời mỗi câu hỏi một cách độc lập.
Bạn có thể hỏi về toàn bộ PR, về các dòng code cụ thể, hoặc về một hình ảnh liên quan đến thay đổi code trong PR.
        """
        # output += "\n\n<table>"
        #
        # # # general
        # # output += "\n\n<tr><td><details> <summary><strong> More PR-Agent commands</strong></summary><hr> \n\n"
        # # output += HelpMessage.get_general_bot_help_text()
        # # output += "\n\n</details></td></tr>\n\n"
        #
        # output += "</table>"

        output += f"\n\nXem [trang sử dụng](https://pr-agent-docs.codium.ai/tools/ask/) ask để có hướng dẫn đầy đủ về cách dùng công cụ này.\n\n"

        return output


    @staticmethod
    def get_improve_usage_guide():
        output = "**Tổng quan:**\n"
        output += "Công cụ đề xuất cải tiến code, có tên `improve`, quét các thay đổi code trong PR, và tự động sinh ra các đề xuất cải tiến cho PR."
        output += "Công cụ có thể được kích hoạt [tự động](https://pr-agent-docs.codium.ai/usage-guide/automations_and_usage/#github-app-automatic-tools-when-a-new-pr-is-opened) mỗi khi một PR mới được mở, hoặc có thể được gọi thủ công bằng cách bình luận trên một PR.\n"
        output += """\
- Khi bình luận, để chỉnh sửa [cấu hình](https://github.com/Codium-ai/pr-agent/blob/main/pr_agent/settings/configuration.toml#L78) liên quan đến công cụ improve (mục `pr_code_suggestions`), dùng mẫu sau:

```
/improve --pr_code_suggestions.some_config1=... --pr_code_suggestions.some_config2=...
```

- Với một [file cấu hình](https://pr-agent-docs.codium.ai/usage-guide/configuration_options/), dùng mẫu sau:

```
[pr_code_suggestions]
some_config1=...
some_config2=...
```

"""

        output += f"\n\nXem [trang sử dụng](https://pr-agent-docs.codium.ai/tools/improve/) improve để có hướng dẫn đầy đủ về cách dùng công cụ này.\n\n"

        return output


    @staticmethod
    def get_help_docs_usage_guide():
        output = "**Tổng quan:**\n"
        output += """\
Công cụ help docs, có tên `help_docs`, trả lời một câu hỏi dựa trên một đường dẫn tương đối tới tài liệu, từ repository của merge request này hoặc từ một repository khác."
Có thể gọi thủ công bằng cách bình luận trên bất kỳ PR nào:
```
/help_docs "..."
```
"""
        output += f"\n\nXem [trang sử dụng](https://pr-agent-docs.codium.ai/tools/help_docs/) help_docs để có hướng dẫn đầy đủ về cách dùng công cụ này.\n\n"
        return output
