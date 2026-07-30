param(
    [string]$InputPbf = "$PSScriptRoot\..\data\raw\osm\china-260325.osm.pbf",
    [string]$OutputJson = "$PSScriptRoot\..\data\generated\railways.geojson",
    [string]$RailwayJourneysJson = "$PSScriptRoot\..\data\source\journeys-railway.json",
    [string]$StationsJson = "$PSScriptRoot\..\data\generated\stations.json",
    [string]$AirportsJson = "$PSScriptRoot\..\data\generated\airports.json",
    [string]$PassengerStationNames = "$PSScriptRoot\..\data\source\station_name.js",
    [string]$RoutesJson = "$PSScriptRoot\..\data\generated\routes.json",
    [string]$ProvinceBoundarySource = "$PSScriptRoot\..\data\raw\boundaries\china-provinces-datav.json",
    [string]$ProvinceBoundariesJson = "$PSScriptRoot\..\data\generated\admin-boundaries-province.json",
    [double]$Tolerance = 0.005,
    [double]$MinimumLengthKm = 2.0,
    [string]$Snapshot = "2026-03-25"
)

$ErrorActionPreference = "Stop"
$buildDirectory = Join-Path $PSScriptRoot "..\data\cache"
$railPbf = Join-Path $buildDirectory "railways.osm.pbf"
$railSequence = Join-Path $buildDirectory "railways.geojsonseq"
$placesPbf = Join-Path $buildDirectory "places.osm.pbf"
$placesSequence = Join-Path $buildDirectory "places.geojsonseq"
$stationBuilder = Join-Path $PSScriptRoot "builders\build_passenger_stations.py"
$airportBuilder = Join-Path $PSScriptRoot "builders\build_airports.py"
$railwayBuilder = Join-Path $PSScriptRoot "builders\build_railway_layer.py"
$routeBuilder = Join-Path $PSScriptRoot "builders\build_journey_routes.py"
$boundaryBuilder = Join-Path $PSScriptRoot "builders\build_admin_boundaries.py"
$condaBase = (conda info --base).Trim()
$basePython = Join-Path $condaBase "python.exe"
if (-not (Test-Path -LiteralPath $basePython)) {
    throw "Base Python was not found at $basePython"
}

New-Item -ItemType Directory -Path $buildDirectory -Force | Out-Null

Write-Host "Filtering railway ways from $InputPbf"
conda run -n osmium osmium tags-filter $InputPbf w/railway=rail -o $railPbf -O
if ($LASTEXITCODE -ne 0) {
    throw "Osmium railway filtering failed."
}

Write-Host "Exporting railway LineStrings"
conda run -n osmium osmium export $railPbf --geometry-types=linestring -f geojsonseq -o $railSequence -O
if ($LASTEXITCODE -ne 0) {
    throw "Osmium GeoJSON sequence export failed."
}

Write-Host "Extracting railway stations and airports"
conda run -n osmium osmium tags-filter $InputPbf `
    nwr/railway=station,halt `
    nwr/aeroway=aerodrome `
    -o $placesPbf -O
if ($LASTEXITCODE -ne 0) {
    throw "Osmium place filtering failed."
}

Write-Host "Exporting places with stable OSM ids"
conda run -n osmium osmium export $placesPbf `
    -u type_id `
    -f geojsonseq `
    -o $placesSequence -O
if ($LASTEXITCODE -ne 0) {
    throw "Osmium place export failed."
}

Write-Host "Building nationwide passenger station catalog"
& $basePython $stationBuilder `
    --stations $placesSequence `
    --railways $railSequence `
    --china-boundary $ProvinceBoundarySource `
    --passenger-whitelist $PassengerStationNames `
    --output $StationsJson `
    --snapshot $Snapshot
if ($LASTEXITCODE -ne 0) {
    throw "Passenger station catalog generation failed."
}

Write-Host "Building nationwide scheduled-passenger airport catalog"
& $basePython $airportBuilder `
    --aerodromes $placesSequence `
    --china-boundary $ProvinceBoundarySource `
    --output $AirportsJson `
    --snapshot $Snapshot
if ($LASTEXITCODE -ne 0) {
    throw "Passenger airport catalog generation failed."
}

Write-Host "Building compact MapLibre railway layer"
& $basePython $railwayBuilder `
    --input $railSequence `
    --output $OutputJson `
    --tolerance $Tolerance `
    --min-length-km $MinimumLengthKm `
    --snapshot $Snapshot
if ($LASTEXITCODE -ne 0) {
    throw "Railway layer conversion failed."
}

Write-Host "Building the interactive province map"
& $basePython $boundaryBuilder `
    --province-input $ProvinceBoundarySource `
    --province-output $ProvinceBoundariesJson `
    --snapshot $Snapshot
if ($LASTEXITCODE -ne 0) {
    throw "Administrative boundary generation failed."
}

Write-Host "Routing train journeys over the railway graph"
& $basePython $routeBuilder `
    --railways $railSequence `
    --stations $StationsJson `
    --railway-journeys $RailwayJourneysJson `
    --output $RoutesJson
if ($LASTEXITCODE -ne 0) {
    throw "Train journey routing failed."
}

Write-Host "Created:"
Write-Host "  $StationsJson"
Write-Host "  $AirportsJson"
Write-Host "  $OutputJson"
Write-Host "  $RoutesJson"
Write-Host "  $ProvinceBoundariesJson"
