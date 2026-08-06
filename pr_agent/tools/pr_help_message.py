import copy
import re
from functools import partial
from pathlib import Path

from jinja2 import Environment, StrictUndefined

from pr_agent.algo import MAX_TOKENS
from pr_agent.algo.ai_handlers.base_ai_handler import BaseAiHandler
from pr_agent.algo.ai_handlers.litellm_ai_handler import LiteLLMAIHandler
from pr_agent.algo.pr_processing import retry_with_fallback_models
from pr_agent.algo.token_handler import TokenHandler
from pr_agent.algo.utils import ModelType, clip_tokens, load_yaml, get_max_tokens
from pr_agent.config_loader import get_settings
from pr_agent.git_providers import BitbucketServerProvider, GithubProvider, get_git_provider_with_context
from pr_agent.log import get_logger


def extract_header(snippet):
    res = ''
    lines = snippet.split('===Snippet content===')[0].split('\n')
    highest_header = ''
    highest_level = float('inf')
    for line in lines[::-1]:
        line = line.strip()
        if line.startswith('Header '):
            highest_header = line.split(': ')[1]
    if highest_header:
        res = f"#{highest_header.lower().replace(' ', '-')}"
    return res

class PRHelpMessage:
    def __init__(self, pr_url: str, args=None, ai_handler: partial[BaseAiHandler,] = LiteLLMAIHandler, return_as_string=False):
        self.git_provider = get_git_provider_with_context(pr_url)
        self.ai_handler = ai_handler()
        self.question_str = self.parse_args(args)
        self.return_as_string = return_as_string
        if self.question_str:
            self.vars = {
                "question": self.question_str,
                "snippets": "",
            }
            self.token_handler = TokenHandler(None,
                                              self.vars,
                                              get_settings().pr_help_prompts.system,
                                              get_settings().pr_help_prompts.user)

    async def _prepare_prediction(self, model: str):
        try:
            variables = copy.deepcopy(self.vars)
            environment = Environment(undefined=StrictUndefined)
            system_prompt = environment.from_string(get_settings().pr_help_prompts.system).render(variables)
            user_prompt = environment.from_string(get_settings().pr_help_prompts.user).render(variables)
            response, finish_reason = await self.ai_handler.chat_completion(
                model=model, temperature=get_settings().config.temperature, system=system_prompt, user=user_prompt)
            return response
        except Exception as e:
            get_logger().error(f"Error while preparing prediction: {e}")
            return ""

    def parse_args(self, args):
        if args and len(args) > 0:
            question_str = " ".join(args)
        else:
            question_str = ""
        return question_str

    def format_markdown_header(self, header: str) -> str:
        try:
            # First, strip common characters from both ends
            cleaned = header.strip('# 💎\n')

            # Define all characters to be removed/replaced in a single pass
            replacements = {
                "'": '',
                "`": '',
                '(': '',
                ')': '',
                ',': '',
                '.': '',
                '?': '',
                '!': '',
                ' ': '-'
            }

            # Compile regex pattern for characters to remove
            pattern = re.compile('|'.join(map(re.escape, replacements.keys())))

            # Perform replacements in a single pass and convert to lowercase
            return pattern.sub(lambda m: replacements[m.group()], cleaned).lower()
        except Exception:
            get_logger().exception(f"Error while formatting markdown header", artifacts={'header': header})
            return ""


    async def run(self):
        try:
            if self.question_str:
                get_logger().info(f'Answering a PR question about the PR {self.git_provider.pr_url} ')

                if not get_settings().get('openai.key'):
                    if get_settings().config.publish_output:
                        self.git_provider.publish_comment(
                            "Tính năng chat của công cụ `Help` yêu cầu khóa API OpenAI để tính embedding")
                    else:
                        get_logger().error("The `Help` tool chat feature requires an OpenAI API key for calculating embeddings")
                    return

                # current path
                docs_path= Path(__file__).parent.parent.parent / 'docs' / 'docs'
                # get all the 'md' files inside docs_path and its subdirectories
                md_files = list(docs_path.glob('**/*.md'))
                folders_to_exclude = ['/finetuning_benchmark/']
                files_to_exclude = {'EXAMPLE_BEST_PRACTICE.md', 'compression_strategy.md', '/docs/overview/index.md'}
                md_files = [file for file in md_files if not any(folder in str(file) for folder in folders_to_exclude) and not any(file.name == file_to_exclude for file_to_exclude in files_to_exclude)]

                # sort the 'md_files' so that 'priority_files' will be at the top
                priority_files_strings = ['/docs/index.md', '/usage-guide', 'tools/describe.md', 'tools/review.md',
                                          'tools/improve.md', '/faq']
                md_files_priority = [file for file in md_files if
                                     any(priority_string in str(file) for priority_string in priority_files_strings)]
                md_files_not_priority = [file for file in md_files if file not in md_files_priority]
                md_files = md_files_priority + md_files_not_priority

                docs_prompt = ""
                for file in md_files:
                    try:
                        with open(file, 'r') as f:
                            file_path = str(file).replace(str(docs_path), '')
                            docs_prompt += f"\n==file name==\n\n{file_path}\n\n==file content==\n\n{f.read().strip()}\n=========\n\n"
                    except Exception as e:
                        get_logger().error(f"Error while reading the file {file}: {e}")
                token_count = self.token_handler.count_tokens(docs_prompt)
                get_logger().debug(f"Token count of full documentation website: {token_count}")

                model = get_settings().config.model
                if model in MAX_TOKENS:
                    max_tokens_full = MAX_TOKENS[model] # note - here we take the actual max tokens, without any reductions. we do aim to get the full documentation website in the prompt
                else:
                    max_tokens_full = get_max_tokens(model)
                delta_output = 2000
                if token_count > max_tokens_full - delta_output:
                    get_logger().info(f"Token count {token_count} exceeds the limit {max_tokens_full - delta_output}. Skipping the PR Help message.")
                    docs_prompt = clip_tokens(docs_prompt, max_tokens_full - delta_output)
                self.vars['snippets'] = docs_prompt.strip()

                # run the AI model
                response = await retry_with_fallback_models(self._prepare_prediction, model_type=ModelType.REGULAR)
                response_yaml = load_yaml(response)
                if isinstance(response_yaml, str):
                    get_logger().warning(f"failing to parse response: {response_yaml}, publishing the response as is")
                    if get_settings().config.publish_output:
                        answer_str = f"### Câu hỏi: \n{self.question_str}\n\n"
                        answer_str += f"### Trả lời:\n\n"
                        answer_str += response_yaml
                        self.git_provider.publish_comment(answer_str)
                    return ""
                response_str = response_yaml.get('response')
                relevant_sections = response_yaml.get('relevant_sections')

                if not relevant_sections:
                    get_logger().info(f"Could not find relevant answer for the question: {self.question_str}")
                    if get_settings().config.publish_output:
                        answer_str = f"### Câu hỏi: \n{self.question_str}\n\n"
                        answer_str += f"### Trả lời:\n\n"
                        answer_str += f"Không tìm thấy thông tin liên quan để trả lời câu hỏi này. Vui lòng cung cấp thêm chi tiết và thử lại."
                        self.git_provider.publish_comment(answer_str)
                    return ""

                # prepare the answer
                answer_str = ""
                if response_str:
                    answer_str += f"### Câu hỏi: \n{self.question_str}\n\n"
                    answer_str += f"### Trả lời:\n{response_str.strip()}\n\n"
                    answer_str += f"#### Nguồn liên quan:\n\n"
                    base_path = "https://qodo-merge-docs.qodo.ai/"
                    for section in relevant_sections:
                        file = section.get('file_name').strip().removesuffix('.md')
                        if str(section['relevant_section_header_string']).strip():
                            markdown_header = self.format_markdown_header(section['relevant_section_header_string'])
                            answer_str += f"> - {base_path}{file}#{markdown_header}\n"
                        else:
                            answer_str += f"> - {base_path}{file}\n"


                # publish the answer
                if get_settings().config.publish_output:
                    self.git_provider.publish_comment(answer_str)
                else:
                    get_logger().info(f"Answer:\n{answer_str}")
            else:
                if not isinstance(self.git_provider, BitbucketServerProvider) and not self.git_provider.is_supported("gfm_markdown"):
                    self.git_provider.publish_comment(
                        "Công cụ `Help` yêu cầu gfm markdown, tính năng này không được nền tảng code của bạn hỗ trợ.")
                    return

                get_logger().info('Getting PR Help Message...')
                relevant_configs = {'pr_help': dict(get_settings().pr_help),
                                    'config': dict(get_settings().config)}
                get_logger().debug("Relevant configs", artifacts=relevant_configs)
                pr_comment = "## Hướng dẫn PR Agent 🤖\n\n"
                pr_comment += "Chào mừng đến với PR Agent, một công cụ dùng AI để tự động phân tích, phản hồi, đề xuất pull request và nhiều hơn nữa."""
                pr_comment += "\n\nDưới đây là danh sách các công cụ bạn có thể dùng để tương tác với PR Agent:\n"
                base_path = "https://pr-agent-docs.codium.ai/tools"

                tool_names = []
                tool_names.append(f"[DESCRIBE]({base_path}/describe/)")
                tool_names.append(f"[REVIEW]({base_path}/review/)")
                tool_names.append(f"[IMPROVE]({base_path}/improve/)")
                tool_names.append(f"[UPDATE CHANGELOG]({base_path}/update_changelog/)")
                tool_names.append(f"[HELP DOCS]({base_path}/help_docs/)")
                tool_names.append(f"[ADD DOCS]({base_path}/add_docs/)")
                tool_names.append(f"[ASK]({base_path}/ask/)")
                tool_names.append(f"[GENERATE CUSTOM LABELS]({base_path}/generate_labels/)")

                descriptions = []
                descriptions.append("Sinh mô tả PR - tiêu đề, loại, tóm tắt, walkthrough code và nhãn")
                descriptions.append("Phản hồi tùy chỉnh về PR, các vấn đề có thể xảy ra, vấn đề bảo mật, công sức đánh giá và nhiều hơn")
                descriptions.append("Đề xuất cải tiến code cho PR")
                descriptions.append("Tự động cập nhật changelog")
                descriptions.append("Trả lời câu hỏi về repository này, hoặc một repository khác, dựa trên đường dẫn tài liệu được cung cấp")
                descriptions.append("Sinh tài liệu cho các phương thức/hàm/lớp đã thay đổi trong PR")
                descriptions.append("Trả lời câu hỏi dạng văn bản tự do về PR")
                descriptions.append("Sinh nhãn tùy chỉnh cho PR, dựa trên hướng dẫn cụ thể do người dùng định nghĩa")

                commands  =[]
                commands.append("`/describe`")
                commands.append("`/review`")
                commands.append("`/improve`")
                commands.append("`/update_changelog`")
                commands.append("`/help_docs`")
                commands.append("`/add_docs`")
                commands.append("`/ask`")
                commands.append("`/generate_labels`")

                checkbox_list = []
                checkbox_list.append(" - [ ] Run <!-- /describe -->")
                checkbox_list.append(" - [ ] Run <!-- /review -->")
                checkbox_list.append(" - [ ] Run <!-- /improve -->")
                checkbox_list.append(" - [ ] Run <!-- /update_changelog -->")
                checkbox_list.append(" - [ ] Run <!-- /help_docs -->")
                checkbox_list.append(" - [ ] Run <!-- /add_docs -->")
                checkbox_list.append("[*]")
                checkbox_list.append("[*]")
                checkbox_list.append("[*]")
                checkbox_list.append("[*]")
                checkbox_list.append("[*]")

                if isinstance(self.git_provider, GithubProvider) and not get_settings().config.get('disable_checkboxes', False):
                    pr_comment += f"<table><tr align='left'><th align='left'>Công cụ</th><th align='left'>Mô tả</th><th align='left'>Kích hoạt tương tác :gem:</th></tr>"
                    for i in range(len(tool_names)):
                        pr_comment += f"\n<tr><td align='left'>\n\n<strong>{tool_names[i]}</strong></td>\n<td>{descriptions[i]}</td>\n<td>\n\n{checkbox_list[i]}\n</td></tr>"
                    pr_comment += "</table>\n\n"
                    pr_comment += f"""\n\n(1) Lưu ý rằng mỗi công cụ có thể được [kích hoạt tự động](https://pr-agent-docs.codium.ai/usage-guide/automations_and_usage/#github-app-automatic-tools-when-a-new-pr-is-opened) khi một PR mới được mở, hoặc gọi thủ công bằng cách [bình luận trên PR](https://pr-agent-docs.codium.ai/usage-guide/automations_and_usage/#online-usage)."""
                    pr_comment += f"""\n\n(2) Các công cụ đánh dấu [*] yêu cầu truyền thêm tham số. Ví dụ, để gọi công cụ `/ask`, bạn cần bình luận trên PR: `/ask "<nội dung câu hỏi>"`. Xem tài liệu liên quan của từng công cụ để biết thêm chi tiết."""
                elif isinstance(self.git_provider, BitbucketServerProvider):
                    # only support basic commands in BBDC
                    pr_comment = generate_bbdc_table(tool_names[:4], descriptions[:4])
                else:
                    pr_comment += f"<table><tr align='left'><th align='left'>Công cụ</th><th align='left'>Lệnh</th><th align='left'>Mô tả</th></tr>"
                    for i in range(len(tool_names)):
                        pr_comment += f"\n<tr><td align='left'>\n\n<strong>{tool_names[i]}</strong></td><td>{commands[i]}</td><td>{descriptions[i]}</td></tr>"
                    pr_comment += "</table>\n\n"
                    pr_comment += f"""\n\nLưu ý rằng mỗi công cụ có thể được [gọi tự động](https://pr-agent-docs.codium.ai/usage-guide/automations_and_usage/) khi một PR mới được mở, hoặc gọi thủ công bằng cách [bình luận trên PR](https://pr-agent-docs.codium.ai/usage-guide/automations_and_usage/#online-usage)."""

                if get_settings().config.publish_output:
                    self.git_provider.publish_comment(pr_comment)
        except Exception as e:
            get_logger().exception(f"Error while running PRHelpMessage: {e}")
        return ""

    async def prepare_relevant_snippets(self, sim_results):
        # Get relevant snippets
        relevant_snippets_full = []
        relevant_pages_full = []
        relevant_snippets_full_header = []
        th = 0.75
        for s in sim_results:
            page = s[0].metadata['source']
            content = s[0].page_content
            score = s[1]
            relevant_snippets_full.append(content)
            relevant_snippets_full_header.append(extract_header(content))
            relevant_pages_full.append(page)
        # build the snippets string
        relevant_snippets_str = ""
        for i, s in enumerate(relevant_snippets_full):
            relevant_snippets_str += f"Snippet {i+1}:\n\n{s}\n\n"
            relevant_snippets_str += "-------------------\n\n"
        return relevant_pages_full, relevant_snippets_full_header, relevant_snippets_str


def generate_bbdc_table(column_arr_1, column_arr_2):
    # Generating header row
    header_row = "| Công cụ  | Mô tả | \n"

    # Generating separator row
    separator_row = "|--|--|\n"

    # Generating data rows
    data_rows = ""
    max_len = max(len(column_arr_1), len(column_arr_2))
    for i in range(max_len):
        col1 = column_arr_1[i] if i < len(column_arr_1) else ""
        col2 = column_arr_2[i] if i < len(column_arr_2) else ""
        data_rows += f"| {col1} | {col2} |\n"

    # Combine all parts to form the complete table
    markdown_table = header_row + separator_row + data_rows
    return markdown_table
