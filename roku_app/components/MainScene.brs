' Plays the master feed full screen. If the stream errors or ends
' (e.g. the master stack restarts), it reconnects every few seconds.

sub init()
    m.video  = m.top.findNode("videoPlayer")
    m.status = m.top.findNode("status")
    m.retry  = m.top.findNode("retryTimer")
    m.video.observeField("state", "OnVideoState")
    m.retry.observeField("fire", "StartVideo")
    m.top.setFocus(true)
end sub

sub OnStreamUrl()
    StartVideo()
end sub

sub StartVideo()
    content = CreateObject("roSGNode", "ContentNode")
    content.url          = m.top.streamUrl
    content.streamFormat = "hls"
    content.live         = true
    m.video.control = "stop"
    m.video.content = content
    m.video.control = "play"
end sub

sub OnVideoState()
    s = m.video.state
    print "[VizelVision] video state: " s
    if s = "playing"
        m.status.visible = false
    else if s = "error" or s = "finished"
        if s = "error"
            print "[VizelVision] error " m.video.errorCode " " m.video.errorMsg
        end if
        m.status.text = "Master feed unavailable, reconnecting..."
        m.status.visible = true
        m.retry.control = "start"
    else if s = "buffering"
        m.status.visible = false
    end if
end sub

' OK / Play restarts the stream (jumps back to the live edge).
function onKeyEvent(key as String, press as Boolean) as Boolean
    if not press then return false
    if key = "OK" or key = "play"
        StartVideo()
        return true
    end if
    return false
end function
