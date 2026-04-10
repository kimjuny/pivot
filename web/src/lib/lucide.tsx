import * as React from "react";
import {
  AlertCircle as AlertCircleIcon,
  AlertTriangle as AlertTriangleIcon,
  ArrowRight as ArrowRightIcon,
  ArrowLeft as ArrowLeftIcon,
  ArrowUp as ArrowUpIcon,
  Bot as BotIcon,
  Brain as BrainIcon,
  BugPlay as BugPlayIcon,
  Check as CheckIcon,
  CheckCircle2 as CheckCircle2Icon,
  ChevronDown as ChevronDownIcon,
  ChevronLeft as ChevronLeftIcon,
  ChevronRight as ChevronRightIcon,
  ChevronUp as ChevronUpIcon,
  ChevronsUpDown as ChevronsUpDownIcon,
  Circle as CircleIcon,
  Copy as CopyIcon,
  Download as DownloadIcon,
  Expand as ExpandIcon,
  ExternalLink as ExternalLinkIcon,
  Eye as EyeIcon,
  EyeOff as EyeOffIcon,
  FileSpreadsheet as FileSpreadsheetIcon,
  FileText as FileTextIcon,
  Folder as FolderIcon,
  FolderUp as FolderUpIcon,
  Github as GithubIcon,
  History as HistoryIcon,
  Globe as GlobeIcon,
  Globe2 as Globe2Icon,
  ImagePlus as ImagePlusIcon,
  Inbox as InboxIcon,
  Info as InfoIcon,
  KeyRound as KeyRoundIcon,
  Layers as LayersIcon,
  Link2 as Link2Icon,
  ListTodo as ListTodoIcon,
  Loader2 as Loader2Icon,
  Lock as LockIcon,
  LogIn as LogInIcon,
  LogOut as LogOutIcon,
  Maximize2 as Maximize2Icon,
  MessageSquare as MessageSquareIcon,
  Minimize2 as Minimize2Icon,
  Minus as MinusIcon,
  Moon as MoonIcon,
  MoreHorizontal as MoreHorizontalIcon,
  PanelLeft as PanelLeftIcon,
  Paperclip as PaperclipIcon,
  Pencil as PencilIcon,
  Pin as PinIcon,
  PinOff as PinOffIcon,
  Plus as PlusIcon,
  Presentation as PresentationIcon,
  Radio as RadioIcon,
  RefreshCcw as RefreshCcwIcon,
  RefreshCw as RefreshCwIcon,
  Search as SearchIcon,
  Server as ServerIcon,
  Settings2 as Settings2Icon,
  Share2 as Share2Icon,
  Square as SquareIcon,
  SquarePen as SquarePenIcon,
  Sun as SunIcon,
  Trash2 as Trash2Icon,
  Upload as UploadIcon,
  User as UserIcon,
  Wrench as WrenchIcon,
  X as XIcon,
  XCircle as XCircleIcon,
  Zap as ZapIcon,
  type LucideIcon,
  type LucideProps,
} from "lucide-react";

/**
 * Keeps Lucide icons visually consistent across the app by enforcing one line
 * weight, regardless of where a page imports the icon.
 */
function withDefaultStroke(Icon: LucideIcon) {
  const Wrapped = React.forwardRef<SVGSVGElement, LucideProps>((props, ref) => (
    <Icon ref={ref} {...props} strokeWidth={1.5} />
  ));

  Wrapped.displayName = Icon.displayName ?? Icon.name;

  return Wrapped as LucideIcon;
}

export const AlertCircle = withDefaultStroke(AlertCircleIcon);
export const AlertTriangle = withDefaultStroke(AlertTriangleIcon);
export const ArrowRight = withDefaultStroke(ArrowRightIcon);
export const ArrowLeft = withDefaultStroke(ArrowLeftIcon);
export const ArrowUp = withDefaultStroke(ArrowUpIcon);
export const Bot = withDefaultStroke(BotIcon);
export const Brain = withDefaultStroke(BrainIcon);
export const BugPlay = withDefaultStroke(BugPlayIcon);
export const Check = withDefaultStroke(CheckIcon);
export const CheckCircle2 = withDefaultStroke(CheckCircle2Icon);
export const ChevronDown = withDefaultStroke(ChevronDownIcon);
export const ChevronLeft = withDefaultStroke(ChevronLeftIcon);
export const ChevronRight = withDefaultStroke(ChevronRightIcon);
export const ChevronUp = withDefaultStroke(ChevronUpIcon);
export const ChevronsUpDown = withDefaultStroke(ChevronsUpDownIcon);
export const Circle = withDefaultStroke(CircleIcon);
export const Copy = withDefaultStroke(CopyIcon);
export const Download = withDefaultStroke(DownloadIcon);
export const Expand = withDefaultStroke(ExpandIcon);
export const ExternalLink = withDefaultStroke(ExternalLinkIcon);
export const Eye = withDefaultStroke(EyeIcon);
export const EyeOff = withDefaultStroke(EyeOffIcon);
export const FileSpreadsheet = withDefaultStroke(FileSpreadsheetIcon);
export const FileText = withDefaultStroke(FileTextIcon);
export const Folder = withDefaultStroke(FolderIcon);
export const FolderUp = withDefaultStroke(FolderUpIcon);
export const Github = withDefaultStroke(GithubIcon);
export const History = withDefaultStroke(HistoryIcon);
export const Globe = withDefaultStroke(GlobeIcon);
export const Globe2 = withDefaultStroke(Globe2Icon);
export const ImagePlus = withDefaultStroke(ImagePlusIcon);
export const Inbox = withDefaultStroke(InboxIcon);
export const Info = withDefaultStroke(InfoIcon);
export const KeyRound = withDefaultStroke(KeyRoundIcon);
export const Layers = withDefaultStroke(LayersIcon);
export const Link2 = withDefaultStroke(Link2Icon);
export const ListTodo = withDefaultStroke(ListTodoIcon);
export const Loader2 = withDefaultStroke(Loader2Icon);
export const Lock = withDefaultStroke(LockIcon);
export const LogIn = withDefaultStroke(LogInIcon);
export const LogOut = withDefaultStroke(LogOutIcon);
export const Maximize2 = withDefaultStroke(Maximize2Icon);
export const MessageSquare = withDefaultStroke(MessageSquareIcon);
export const Minimize2 = withDefaultStroke(Minimize2Icon);
export const Minus = withDefaultStroke(MinusIcon);
export const Moon = withDefaultStroke(MoonIcon);
export const MoreHorizontal = withDefaultStroke(MoreHorizontalIcon);
export const PanelLeft = withDefaultStroke(PanelLeftIcon);
export const Paperclip = withDefaultStroke(PaperclipIcon);
export const Pencil = withDefaultStroke(PencilIcon);
export const Pin = withDefaultStroke(PinIcon);
export const PinOff = withDefaultStroke(PinOffIcon);
export const Plus = withDefaultStroke(PlusIcon);
export const Presentation = withDefaultStroke(PresentationIcon);
export const Radio = withDefaultStroke(RadioIcon);
export const RefreshCcw = withDefaultStroke(RefreshCcwIcon);
export const RefreshCw = withDefaultStroke(RefreshCwIcon);
export const Search = withDefaultStroke(SearchIcon);
export const Server = withDefaultStroke(ServerIcon);
export const Settings2 = withDefaultStroke(Settings2Icon);
export const Share2 = withDefaultStroke(Share2Icon);
export const Square = withDefaultStroke(SquareIcon);
export const SquarePen = withDefaultStroke(SquarePenIcon);
export const Sun = withDefaultStroke(SunIcon);
export const Trash2 = withDefaultStroke(Trash2Icon);
export const Upload = withDefaultStroke(UploadIcon);
export const User = withDefaultStroke(UserIcon);
export const Wrench = withDefaultStroke(WrenchIcon);
export const X = withDefaultStroke(XIcon);
export const XCircle = withDefaultStroke(XCircleIcon);
export const Zap = withDefaultStroke(ZapIcon);

export type { LucideIcon, LucideProps } from "lucide-react";
