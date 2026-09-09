-- 一键截图：按一下就存一张，给鸣潮声骸评分用。
--
-- 按 ¥ 键（JIS 键盘数字键行最右边、delete 左边）截一张，存到 ~/Pictures/EchoShots。
-- 听到「叮」＝存好了，「咚」＝没存上（原因写在 Hammerspoon 控制台里）。
--
-- 想换成别的键：把下面 KEYCODE 改掉，然后菜单栏 Hammerspoon 图标 → Reload Config。
-- JIS 键盘上闲着的键码：93 = ¥，94 = _，102 = 英数，104 = かな（后两个是切输入法的）。

local FOLDER = os.getenv("HOME") .. "/Pictures/EchoShots"
local KEYCODE = 93

hs.fs.mkdir(FOLDER)

local function beep(name)
    local s = hs.sound.getByName(name)
    if s then s:play() end
end

hs.hotkey.bind({}, KEYCODE, function()
    local shot = hs.screen.mainScreen():snapshot()
    if not shot then
        print("截图失败：拿不到画面，多半是屏幕录制权限没给 Hammerspoon")
        beep("Basso")
        return
    end
    local path = string.format("%s/echo-%s.jpg", FOLDER, os.date("%Y%m%d-%H%M%S"))
    if shot:saveToFile(path, "JPEG") then
        -- 评分那个网站每张最多 1MB，这块屏幕存出来 5120x3312、将近 2MB，所以压一道。
        -- 只降压缩率不降分辨率：网站自己说图越清楚识别越准，缩尺寸会伤识别。
        -- 实测质量 40 出来 0.6~0.7MB，留足余量。
        hs.task.new("/usr/bin/sips", nil,
                    {"-s", "format", "jpeg", "-s", "formatOptions", "40", path}):start()
        print("存好了 " .. path)
        beep("Tink")
    else
        print("写不进文件：" .. path)
        beep("Basso")
    end
end)

hs.autoLaunch(true)
hs.alert.show("一键截图已就绪：按 ¥ 存图到 Pictures/EchoShots")
